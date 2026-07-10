"""Local script writer — type a TOPIC in, get an imported, directed project out.

Closes the last non-local gap in "type a script in → video out": the script
itself. The channel's authoring prompt (spec + brief + tone + topic) goes to a
local LLM; the returned storyboard JSON is imported through the normal
create_project path, so the auto-director (assisted mode when the channel says
so) cleans up whatever the model got wrong. The writer only has to produce
narration + picture subjects — by design, a small model is enough.

Two engines, picked automatically:
  1. Ollama, if reachable (config.WRITER.ollama_url) — unloads itself.
  2. transformers in-process (Qwen3-4B-Instruct, auto-downloads ~8 GB into
     ./models on first use; CUDA with CPU fallback, freed after each run).
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Dict, Optional, Tuple

from . import channels, config, jobs, projects

_SYSTEM = ("You write YouTube storyboard JSON. Return ONLY one JSON object — "
           "no markdown fences, no commentary, no thinking. It must parse with "
           "json.loads.")


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen(config.WRITER["ollama_url"] + "/api/tags",
                                    timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def local_model_cached() -> bool:
    name = "models--" + config.WRITER["repo"].replace("/", "--")
    return (config.MODELS_DIR / "hub" / name / "snapshots").exists()


def status() -> Dict:
    return {"ollama": ollama_up(), "ollama_model": config.WRITER["ollama_model"],
            "local_repo": config.WRITER["repo"],
            "local_model_cached": local_model_cached()}


def _ollama_model() -> str:
    """The configured model if pulled, else the best installed fallback
    (prefer a qwen3 chat model over a coder model, else whatever exists)."""
    want = config.WRITER["ollama_model"]
    try:
        with urllib.request.urlopen(config.WRITER["ollama_url"] + "/api/tags",
                                    timeout=4) as r:
            names = [m.get("name", "") for m in json.load(r).get("models", [])]
    except Exception:  # noqa: BLE001
        return want
    if not names or want in names or want.split(":")[0] in {n.split(":")[0] for n in names}:
        return want
    pick = (next((n for n in names if n.startswith("qwen3") and "coder" not in n), None)
            or next((n for n in names if "coder" not in n), None) or names[0])
    print(f"[writer] ollama model {want} not pulled; using {pick}")
    return pick


def _gen_ollama(prompt: str) -> str:
    body = json.dumps({
        "model": _ollama_model(),
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": prompt}],
        "stream": False, "format": "json", "keep_alive": 0,
        "options": {"temperature": config.WRITER["temperature"],
                    "num_predict": config.WRITER["max_new_tokens"],
                    # the authoring spec + research digest need real context;
                    # Ollama's default window silently truncates them
                    "num_ctx": int(config.WRITER.get("num_ctx", 16384))},
    }).encode()
    req = urllib.request.Request(config.WRITER["ollama_url"] + "/api/chat",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)["message"]["content"]


def _gen_transformers(prompt: str, progress) -> str:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    repo = config.WRITER["repo"]
    progress("Loading local writer model" + ("" if local_model_cached()
             else f" (first run — downloading {repo})"), 0.05)
    tok = AutoTokenizer.from_pretrained(repo)
    try:
        model = AutoModelForCausalLM.from_pretrained(
            repo, torch_dtype=torch.bfloat16, device_map="cuda")
    except Exception:  # OOM / no CUDA → slow but working CPU path
        model = AutoModelForCausalLM.from_pretrained(
            repo, torch_dtype=torch.float32, device_map="cpu")
    try:
        msgs = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt}]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_tensors="pt").to(model.device)
        progress("Writing the script", 0.25)
        out = model.generate(ids, max_new_tokens=config.WRITER["max_new_tokens"],
                             do_sample=True, temperature=config.WRITER["temperature"],
                             top_p=0.9, pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids.shape[-1]:], skip_special_tokens=True)
    finally:
        del model
        try:
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass


def _extract_json(text: str) -> Dict:
    """First balanced {...} object in the model output."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in output")
    depth = 0
    in_str = esc = False
    for i, c in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON in output")


def _write_once(prompt: str, progress) -> Tuple[Dict, str]:
    if ollama_up():
        try:
            raw = _gen_ollama(prompt)
            return _extract_json(raw), raw
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            # e.g. the configured model isn't pulled - fall back to in-process
            progress(f"Ollama failed ({exc}); using the in-process writer", 0.05)
    raw = _gen_transformers(prompt, progress)
    return _extract_json(raw), raw


def generate_json(prompt: str, progress) -> Dict:
    """One local-LLM JSON generation (Ollama else in-process transformers) —
    shared by the script writer and the channel roulette."""
    return _write_once(prompt, progress)[0]


def submit_write(cid: str, topic: Optional[str] = None) -> str:
    """Job: channel prompt → local LLM → storyboard → imported project."""
    ch = channels.get(cid)
    if not ch:
        raise ValueError("channel not found")

    def task(progress) -> Dict:
        prompt = channels.authoring_prompt(ch, topic) + (
            "\n\nReturn ONLY the storyboard JSON object described by the spec "
            "(keys: video, scenes, character_bible). No other text.")
        try:
            board, raw = _write_once(prompt, progress)
        except Exception as exc:  # one retry with the error fed back
            progress(f"Retrying (first draft invalid: {exc})", 0.55)
            board, raw = _write_once(
                prompt + f"\n\nYour previous output was invalid ({exc}). "
                         "Output strictly one JSON object this time.", progress)
        (config.OUTPUTS_DIR / "writer_last.json").write_text(
            raw, encoding="utf-8")           # kept for debugging bad drafts
        progress("Importing + auto-directing", 0.9)
        name = (topic or board.get("video", {}).get("title") or "").strip() or None
        project = projects.create_project(board, name=name, channel=cid)
        rep = project.get("direction_report") or {}
        return {"project_id": project["id"], "name": project["name"],
                "scenes": len(project.get("scenes", [])),
                "warnings": (rep.get("warnings") or [])[:6],
                "mode": rep.get("mode")}

    return jobs.submit("write_script", task)
