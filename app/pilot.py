"""AUTOPILOT: a video IDEA in, a finished video out, with a LOCAL agent.

The user's replacement for driving this system with Claude Code (2026-07-10:
"I don't want to waste Claude tokens making videos; Claude focuses on
improving the system, the local agent runs it"). You type an idea into the
Script section (as broad or as detailed as you like); this module does the
rest end to end, spending LLM calls only where a model is genuinely needed
and letting the SYSTEM carry the craft everywhere else (the design principle
in CLAUDE.md):

  1 interpret  idea -> topic, angle, promise, research queries, the 2-5
               integral references whose photos belong in the video (local
               LLM: Ollama if reachable, else in-process Qwen3-4B)
  2 research   Wikipedia facts digest + sources (app/webresearch.py)
  3 script     the channel's authoring prompt (spec + brief + natural-flow
               rules) + the playbook's script method + the research digest ->
               storyboard JSON, written by the local LLM, retried on errors
  4 import     projects.create_project in ASSISTED mode (the auto-director
               may rewrite structure; small-model output expected)
  5 refs       download reference images (people/items/places) into
               research/refs/; the assembler edits each in at first mention
  6 produce    the whole voice->images->score->animate->assemble->grade chain
  7 package    research-driven SEO (packaging.build)

The "Claude skills" ride along as FILES: the same storyboard spec, the
playbook script algorithm, and the channel brief that Claude reads are loaded
into the local model's prompt, so improving those docs improves both drivers.

Run state lives in-process (like produce): POST /api/channels/{cid}/autopilot
starts one, GET /api/autopilot/{aid} polls it, with a rolling log the UI can
show. It is NOT a jobs-queue job (it waits on queue jobs itself).
"""
from __future__ import annotations

import re
import threading
import time
import traceback
from typing import Dict, List, Optional

from . import (channels, config, packaging, produce, projects, storage,
               webresearch, writer)

_state: Dict[str, Dict] = {}
_lock = threading.Lock()


class _Cancelled(Exception):
    """Raised inside a run when the user cancels it from the Queue page."""


def cancel(aid: str) -> bool:
    """Flag a running autopilot; the run stops at its next stage boundary.
    Any produce job currently working for it is cancelled immediately."""
    with _lock:
        st = _state.get(aid)
        if not st or st.get("status") != "running":
            return False
        st["cancel"] = True
        pid = st.get("project_id")
    try:
        from . import jobs as _j
        from . import produce as _pr
        ps = (_pr.status(pid) or {}) if pid else {}
        if ps.get("job_id"):
            _j.cancel(ps["job_id"])
    except Exception:  # noqa: BLE001
        pass
    _log(aid, "cancel requested")
    return True


def _ck(aid: str) -> None:
    with _lock:
        if (_state.get(aid) or {}).get("cancel"):
            raise _Cancelled("cancelled from the Queue page")


# --- state ------------------------------------------------------------------
def status(aid: str) -> Optional[Dict]:
    with _lock:
        st = _state.get(aid)
        return dict(st, log=list(st.get("log") or [])) if st else None


def latest_for(cid: str) -> Optional[Dict]:
    with _lock:
        cands = [s for s in _state.values() if s.get("channel") == cid]
        if not cands:
            return None
        st = max(cands, key=lambda s: s.get("started") or 0)
        return dict(st, log=list(st.get("log") or []))


def _set(aid: str, **kw) -> None:
    with _lock:
        _state.setdefault(aid, {}).update(kw)


def _log(aid: str, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(f"[autopilot {aid}] {msg}")
    with _lock:
        st = _state.setdefault(aid, {})
        st.setdefault("log", []).append(line)
        del st["log"][:-200]


# --- prompt building ----------------------------------------------------------
def _playbook_script_method(max_chars: int = 3500) -> str:
    """The SCRIPT ALGORITHM section of VIDEO_PLAYBOOK.md - the same 'skill'
    Claude reads - trimmed to fit a small model's context."""
    try:
        text = (config.BASE_DIR / "VIDEO_PLAYBOOK.md").read_text(encoding="utf-8")
        m = re.search(r"## 2\. THE SCRIPT ALGORITHM.*?(?=\n---)", text, re.S)
        return (m.group(0) if m else "")[:max_chars]
    except Exception:  # noqa: BLE001
        return ""


def _interpret_prompt(ch: Dict, idea: str) -> str:
    return (
        "You plan a faceless YouTube documentary video.\n"
        f"CHANNEL: {ch.get('name')} - {ch.get('niche', '')}\n"
        f"Channel brief: {ch.get('brief', '')}\n\n"
        f"VIDEO IDEA from the user (may be broad or detailed):\n{idea}\n\n"
        "Decide the strongest single true story that fits the idea and the "
        "channel. Return ONLY this JSON object:\n"
        '{"topic": "one specific story, stated in one line",\n'
        ' "angle": "the single narrative spine: one person / one event / one question",\n'
        ' "promise": "by the end the viewer will know/feel ...",\n'
        ' "wikipedia": ["2 to 4 Wikipedia article titles to research"],\n'
        ' "entities": [{"label": "Full Name", "kind": "person"}]}\n'
        "entities = only the 2 to 5 references whose REAL photo should appear "
        "in the video (the people involved first, then a key place or item). "
        'kind is "person", "place" or "item". If the idea names or implies a '
        "specific real person or event, keep exactly that story; never "
        "substitute a different one.")


def _script_prompt(ch: Dict, plan: Dict, research: Dict, minutes: float) -> str:
    words = int(minutes * 160)
    n_scenes = max(12, int(minutes * 13))
    digest = "\n\n".join(research.get("facts") or [])[:4500]
    parts = [channels.authoring_prompt(ch, topic=plan.get("topic") or "")]
    if digest:
        parts.append(
            "RESEARCH (verified facts - use ONLY these for names, dates and "
            "numbers; if a fact is not in here, do not state it; never invent "
            "quotes):\n" + digest)
    parts.append(f"ANGLE: {plan.get('angle', '')}\nPROMISE: {plan.get('promise', '')}")
    parts.append(f"TARGET LENGTH: about {words} narration words over about "
                 f"{n_scenes} scenes.")
    method = _playbook_script_method()
    if method:
        parts.append("SCRIPT METHOD (the studio's playbook - follow it):\n" + method)
    parts.append("Return ONLY the storyboard JSON object described by the spec "
                 "(keys: video, scenes, character_bible). No other text.")
    return "\n\n---\n\n".join(parts)


# --- LLM helpers ----------------------------------------------------------------
def _llm_json(prompt: str, aid: str, what: str) -> Dict:
    """One local-LLM JSON call with a single feed-the-error-back retry."""
    def prog(stage, frac):
        _set(aid, detail=stage)
    try:
        return writer.generate_json(prompt, prog)
    except Exception as exc:  # noqa: BLE001
        _log(aid, f"{what}: first draft invalid ({exc}); retrying")
        return writer.generate_json(
            prompt + f"\n\nYour previous output was invalid ({exc}). "
                     "Output strictly one JSON object this time.", prog)


def _board_ok(board: Dict) -> Optional[str]:
    scenes = board.get("scenes") or []
    if len(scenes) < 8:
        return f"only {len(scenes)} scenes (need at least 8)"
    total = sum(len((s.get("narration") or "").split()) for s in scenes)
    if total < 120:
        return f"only {total} narration words (need at least 120)"
    return None


# --- the run -------------------------------------------------------------------
def submit(cid: str, idea: str, opts: Optional[Dict] = None) -> str:
    ch = channels.get(cid)
    if not ch:
        raise ValueError("channel not found")
    idea = (idea or "").strip()
    if not idea:
        raise ValueError("Type the video idea first.")
    with _lock:
        if any(s.get("channel") == cid and s.get("status") == "running"
               for s in _state.values()):
            raise ValueError("An autopilot run is already going for this channel.")
    opts = opts or {}
    aid = storage.new_id()[:12]
    _set(aid, id=aid, channel=cid, idea=idea, status="running",
         stage="interpret", started=time.time(), project_id=None,
         result=None, error=None, log=[])

    def run():
        try:
            minutes = float(opts.get("minutes") or 2.0)
            _log(aid, f"idea: {idea[:140]}")

            # 1 interpret ---------------------------------------------------
            _set(aid, stage="interpret")
            _log(aid, "interpreting the idea (local LLM)")
            try:
                plan = _llm_json(_interpret_prompt(ch, idea), aid, "interpret")
            except Exception as exc:  # noqa: BLE001 - degrade to the raw idea
                _log(aid, f"interpret failed ({exc}); using the idea as-is")
                plan = {}
            plan = {"topic": (plan.get("topic") or idea)[:200],
                    "angle": plan.get("angle") or "",
                    "promise": plan.get("promise") or "",
                    "wikipedia": [q for q in (plan.get("wikipedia") or [idea])
                                  if isinstance(q, str)][:4],
                    "entities": [e for e in (plan.get("entities") or [])
                                 if isinstance(e, dict) and e.get("label")][:5]}
            _log(aid, f"topic: {plan['topic']}")

            # 2 research ----------------------------------------------------
            _ck(aid)
            _set(aid, stage="research")
            _log(aid, f"researching: {', '.join(plan['wikipedia'])}")
            research = webresearch.research_topic(plan["wikipedia"])
            _log(aid, f"research: {len(research['facts'])} pages, "
                      f"{len(research['keywords'])} keywords")

            # 3 script ------------------------------------------------------
            _ck(aid)
            _set(aid, stage="script")
            _log(aid, "writing the storyboard (local LLM)")
            prompt = _script_prompt(ch, plan, research, minutes)
            board = _llm_json(prompt, aid, "script")
            bad = _board_ok(board)
            if bad:
                _log(aid, f"draft too thin ({bad}); one rewrite")
                board = _llm_json(
                    prompt + f"\n\nYour previous storyboard was rejected: {bad}. "
                             "Write the FULL storyboard this time.", aid, "script")
                bad = _board_ok(board)
                if bad:
                    raise RuntimeError(f"script failed twice: {bad}")
            (config.OUTPUTS_DIR / "autopilot_last.json").write_text(
                __import__("json").dumps(board, ensure_ascii=False, indent=2),
                encoding="utf-8")

            # 4 import (assisted: the director may rewrite structure) --------
            _ck(aid)
            _set(aid, stage="import")
            project = projects.create_project(
                board, name=plan["topic"], channel=cid,
                engines={"authoring": "assisted"})
            pid = project["id"]
            _set(aid, project_id=pid)
            rep = project.get("direction_report") or {}
            for w in (rep.get("warnings") or [])[:5]:
                _log(aid, f"lint: {w}")
            _log(aid, f"imported project {pid} "
                      f"({len(project.get('scenes') or [])} scenes)")

            # research + the idea ride on the project (SEO is research-driven)
            p = projects.get_project(pid)
            p["research"] = {
                "summary": (plan["promise"] or plan["angle"] or plan["topic"]),
                "facts": [f[:400] for f in research["facts"]][:8],
                "sources": research["sources"],
                "keywords": research["keywords"],
            }
            p["autopilot"] = {"idea": idea, "angle": plan["angle"],
                              "promise": plan["promise"], "run": aid}
            projects.save_project(p)

            # 5 reference images ---------------------------------------------
            if plan["entities"]:
                _set(aid, stage="refs")
                _log(aid, "fetching reference images: " +
                          ", ".join(e["label"] for e in plan["entities"]))
                try:
                    got = webresearch.fetch_refs(pid, plan["entities"])
                    _log(aid, f"refs: {len(got['found'])} found, "
                              f"{len(got['missed'])} missed")
                except Exception as exc:  # noqa: BLE001
                    _log(aid, f"refs skipped ({exc})")

            # 6 produce -------------------------------------------------------
            _ck(aid)
            _set(aid, stage="produce")
            _log(aid, "producing (voice, images, score, animate, assemble, grade)")
            produce.submit_produce(pid)
            t0 = time.time()
            last_stage = ""
            while True:
                st = produce.status(pid) or {}
                stg = str(st.get("stage") or "")
                if stg and stg != last_stage:
                    last_stage = stg
                    _set(aid, detail=stg)
                if st.get("status") == "done":
                    break
                if st.get("status") == "error":
                    raise RuntimeError(f"produce failed: {st.get('error')}")
                if time.time() - t0 > 6 * 3600:
                    raise RuntimeError("produce timed out (6 h)")
                _ck(aid)
                time.sleep(3)
            _log(aid, "produce finished")

            # QA gate: the one-take transcript check must have passed
            p = projects.get_project(pid)
            qa = ((p.get("narration") or {}).get("qa")) or {}
            if qa and not qa.get("ok", True):
                _log(aid, f"WARNING voice QA flagged the take: {qa} - review "
                          "the narration before publishing")

            # 7 package ---------------------------------------------------------
            _set(aid, stage="package")
            try:
                packaging.build(pid)
                _log(aid, "SEO package built")
            except Exception as exc:  # noqa: BLE001
                _log(aid, f"package failed ({exc}) - build it from Publish")

            p = projects.get_project(pid)
            render = ((p.get("renders") or [{}])[0])
            seo_title = ((p.get("seo") or {}).get("titles") or [p.get("name")])[0]
            result = {"project_id": pid, "name": p.get("name"),
                      "file": render.get("file"),
                      "url": f"/projects/{pid}/{render.get('file')}"
                             if render.get("file") else None,
                      "duration": render.get("duration"),
                      "seo_title": seo_title}
            _set(aid, status="done", stage="done", result=result)
            _log(aid, f"DONE: {result.get('url') or pid}")
        except _Cancelled:
            _set(aid, status="cancelled", stage="cancelled")
            _log(aid, "CANCELLED")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            _set(aid, status="error", error=f"{type(exc).__name__}: {exc}")
            _log(aid, f"ERROR: {exc}")

    threading.Thread(target=run, name=f"autopilot-{aid}", daemon=True).start()
    return aid
