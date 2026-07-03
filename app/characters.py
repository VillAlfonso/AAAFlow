"""Character bible — consistent recurring characters across a video.

Each project keeps a list of characters (seeded from the storyboard's
``character_bible`` or added by hand). For each one we generate a **reference
sheet**: an anchor (front, neutral) plus angle + expression variations.

Sheets render on **krea2 via ComfyUI** (the app's only image model since
2026-07-03). Identity holds the krea2 way: one fixed, detailed descriptor in
every prompt + one seed family per character + krea2's very consistent flat
style — the same doctrine scene renders use (character looks come from the
bible descriptors merged into scene prompts by scenes.build_image_prompt).
The old SDXL + IP-Adapter anchor-conditioning path went with cartoon-rag.
"""
from __future__ import annotations

import random
import time
from typing import Callable, Dict, List, Optional

from . import config, jobs, projects, storage
from .comfy_engine import comfy_engine
from .scenes import _slug, normalize_character

ProgressFn = Callable[[str, float], None]

# Each shot: (label, prompt fragment, kind, (width, height)). The first is the
# anchor (front/neutral) every other shot references for identity consistency.
SHEET_SHOTS = [
    ("front", "full body, standing straight facing the camera, front view, neutral calm expression, arms relaxed at sides", "angle", (768, 1024)),
    ("three-quarter", "full body, standing, three-quarter front view turned slightly to the side, neutral expression", "angle", (768, 1024)),
    ("side", "full body, standing, side profile view facing left, neutral expression", "angle", (768, 1024)),
    ("back", "full body, standing, seen from behind, back view", "angle", (768, 1024)),
    ("happy", "close-up portrait, head and shoulders, big happy smile, cheerful joyful expression, front view", "emotion", (768, 768)),
    ("sad", "close-up portrait, head and shoulders, sad downcast unhappy expression, front view", "emotion", (768, 768)),
    ("angry", "close-up portrait, head and shoulders, angry frowning furious expression, front view", "emotion", (768, 768)),
    ("surprised", "close-up portrait, head and shoulders, surprised shocked expression with wide eyes and open mouth, front view", "emotion", (768, 768)),
]

_SHEET_NEG = ("multiple characters, two people, crowd, extra limbs, busy background, "
              "scenery, props, text, words, watermark, signature, photo, realistic, blurry")


# --- CRUD on project["characters"] -----------------------------------------
def list_characters(project: Dict) -> List[Dict]:
    out = []
    pid = project.get("id")
    for c in (project.get("characters") or []):
        refs = []
        for s in (c.get("sheet") or []):
            refs.append({**s, "url": f"/projects/{pid}/{s['file']}"})
        out.append({**c, "sheet": refs,
                    "anchor_url": (f"/projects/{pid}/{c['anchor']}" if c.get("anchor") else None)})
    return out


def get_character(project: Dict, cid: str) -> Optional[Dict]:
    for c in (project.get("characters") or []):
        if c.get("id") == cid:
            return c
    return None


def add_or_update(pid: str, data: Dict) -> Optional[Dict]:
    proj = projects.get_project(pid)
    if not proj:
        return None
    proj.setdefault("characters", [])
    name = (data.get("name") or "").strip()
    cid = (data.get("id") or _slug(name)).strip()
    if not cid:
        raise ValueError("Character needs a name.")
    existing = get_character(proj, cid)
    if existing:
        for k in ("name", "description", "palette", "aliases"):
            if k in data and data[k] is not None:
                existing[k] = data[k]
    else:
        ch = normalize_character(data, len(proj["characters"]))
        ch["id"] = cid
        proj["characters"].append(ch)
        existing = ch
    projects.save_project(proj)
    return existing


def delete_character(pid: str, cid: str) -> bool:
    proj = projects.get_project(pid)
    if not proj:
        return False
    chars = proj.get("characters") or []
    ch = get_character(proj, cid)
    if not ch:
        return False
    pdir = projects.project_dir(pid)
    for s in (ch.get("sheet") or []):
        try:
            (pdir / s["file"]).unlink()
        except OSError:
            pass
    proj["characters"] = [c for c in chars if c.get("id") != cid]
    projects.save_project(proj)
    return True


def seed_from_storyboard(pid: str) -> int:
    """(Re)extract characters from the project's original storyboard source.json."""
    from .scenes import parse_characters
    proj = projects.get_project(pid)
    if not proj:
        raise ValueError("Project not found.")
    src = projects.project_dir(pid) / "source.json"
    if not src.exists():
        return 0
    import json
    raw = json.loads(src.read_text(encoding="utf-8"))
    bible = parse_characters(raw)
    if not bible:
        return 0
    proj.setdefault("characters", [])
    have = {c["id"] for c in proj["characters"]}
    added = 0
    for ch in bible:
        if ch["id"] not in have:
            proj["characters"].append(ch)
            added += 1
    if added:
        projects.save_project(proj)
    return added


# --- reference-sheet generation --------------------------------------------
def submit_character_sheet(pid: str, cid: str, opts: Optional[Dict] = None) -> str:
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    ch = get_character(project, cid)
    if not ch:
        raise ValueError("Character not found.")
    if not (ch.get("description") or "").strip():
        raise ValueError("Give the character a description (its fixed look) first.")
    opts = dict(opts or {})

    def task(progress: ProgressFn) -> Dict:
        # krea2 (ComfyUI): identity = fixed descriptor + one seed family +
        # krea2's consistent flat style. The project's own art direction leads.
        mdef = config.IMAGE_BASES["krea2"]

        proj = projects.get_project(pid)
        c = get_character(proj, cid)
        c["status"] = "generating"
        projects.save_project(proj)
        style = ((proj.get("video") or {}).get("global_style_suffix")
                 or "").strip() or config.KREA2_STYLE

        pdir = projects.project_dir(pid)
        (pdir / "characters").mkdir(parents=True, exist_ok=True)
        base = ", ".join(p for p in [c.get("name"), c.get("description"), c.get("palette")] if p)

        progress("Starting ComfyUI / krea2…", 0.03)
        comfy_engine.ensure_running(progress=lambda s, f: progress(s, 0.03 + 0.12 * f))

        seed0 = int(opts.get("seed", -1))
        if seed0 < 0:
            seed0 = random.randint(0, 2**31 - 1)

        shots = SHEET_SHOTS
        sheet: List[Dict] = []
        n = len(shots)
        for i, (label, frag, kind, (w, h)) in enumerate(shots):
            progress(f"Drawing {c['name']} · {label} ({i + 1}/{n})", 0.15 + 0.8 * i / n)
            prompt = (f"{base}. {frag}. single character, full character reference, "
                      f"plain solid white background. {style}")
            img = comfy_engine.generate(
                prompt, _SHEET_NEG, width=w, height=h,
                steps=int(mdef["steps"]), guidance=float(mdef["guidance"]),
                seed=seed0 + i, mdef=mdef)
            rel = f"characters/{cid}_{label}.png"
            img.save(str(pdir / rel))
            if i == 0:
                c["anchor"] = rel
            sheet.append({"file": rel, "label": label, "kind": kind})

        c["sheet"] = sheet
        c["status"] = "ready"
        c["updated"] = time.time()
        projects.save_project(proj)

        storage.add_history({
            "id": storage.new_id(), "created": time.time(), "preview": False,
            "kind": "character", "project": pid, "project_name": proj.get("name"),
            "text_preview": f"Generated reference sheet for {c['name']} ({len(sheet)} shots)",
        })
        return {"character": cid, "shots": len(sheet)}

    return jobs.submit("character_sheet", task)


# --- retrieval at scene-render time ----------------------------------------
def _index(project: Dict) -> Dict[str, Dict]:
    idx = {}
    for c in (project.get("characters") or []):
        if not c.get("sheet"):
            continue
        for nm in [c.get("name", "")] + (c.get("aliases") or []):
            if nm:
                idx[nm.strip().lower()] = c
    return idx


def _pick(c: Dict, expression: str, k: int) -> List[str]:
    """Anchor (identity) first, then the sheet shot best matching the expression."""
    sheet = c.get("sheet") or []
    expr = (expression or "").lower()
    picks: List[str] = []
    if c.get("anchor"):
        picks.append(c["anchor"])
    if expr:
        emo = [s for s in sheet if s["kind"] == "emotion"]
        best = max(emo, key=lambda s: (s["label"] in expr or expr in s["label"]),
                   default=None)
        if best and (best["label"] in expr or expr in best["label"]):
            picks.append(best["file"])
    for s in sheet:                       # backfill toward k with clear angles
        if len(picks) >= k:
            break
        if s["file"] not in picks and s["label"] in ("front", "three-quarter"):
            picks.append(s["file"])
    # de-dup, keep order
    seen, out = set(), []
    for p in picks:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:k]


def retrieve_for_scene(project: Dict, scene: Dict, k_per_char: int = 2,
                       max_refs: int = 4) -> List[str]:
    """Absolute paths of character references for the characters a scene features."""
    idx = _index(project)
    if not idx:
        return []
    pdir = projects.project_dir(project["id"])
    refs: List[str] = []
    for sc in (scene.get("characters") or []):
        name = (sc.get("name") if isinstance(sc, dict) else sc) or ""
        c = idx.get(name.strip().lower())
        if not c:
            continue
        expr = sc.get("expression", "") if isinstance(sc, dict) else ""
        for rel in _pick(c, expr, k_per_char):
            ap = str(pdir / rel)
            if ap not in refs:
                refs.append(ap)
    return refs[:max_refs]


def has_sheets(project: Dict) -> bool:
    return any(c.get("sheet") for c in (project.get("characters") or []))
