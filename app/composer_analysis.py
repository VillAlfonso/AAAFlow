"""THE TRUE VIDEO ANALYZER: how a channel turns narration into pictures.

User, 2026-07-14: "study the scene, see how the youtuber took inspiration
from, draw and present the information whilst taking into account what the
narrator says… once the analyzer analyzed the clips scene by scene it should
also analyze the video as a whole, how they all connect, reading between the
lines."

The gatherer measures WHAT is on screen (cuts, motion, media class). It never
asked the only question a composer cares about:

    the narrator said THIS. why did the editor show THAT?

This module answers it in two passes.

PASS 1 — shot by shot. Every shot is paired with the exact narration spoken
over it (segments carry start/end times, shots carry boundaries), a frame is
pulled from the middle of the shot, and both go to the local VLM together.
For each shot it records what is depicted, the DEVICE used (reconstruction /
archival / document / map / typeset card…), the RELATION to the line (literal
/ evidence / metaphor / context / reaction / transition), the framing, and a
one-line WHY. That relation field is the whole point: it is the difference
between "they showed a coin" and "they answer a money claim with a physical
object, in macro, every time".

PASS 2 — the video as a whole. The ordered (line -> picture -> relation)
record is folded into the architecture: acts and their function, how the
opening and closing work, recurring spaces and characters, callbacks (a setup
paid off later), and the rhythm of literal versus metaphor. Out of that comes
`rules_for_composer` — the actionable instructions the composer follows when
it writes image prompts for OUR videos.

Output per pack: `composition.json` + `composition.md` in the gather folder.
A study folds these into the channel's composition skill.

Local VLM (Ollama) does pass 1; pass 2 is written by whatever intelligence
reads the record (Claude, or the local LLM as a fallback) — the record itself
is plain JSON, so any model can consume it. Zero cloud requirement.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import config, jobs, storage, vlm
from .gatherer import GATHER_DIR

DEVICES = ["reconstruction-3d", "archival-photo", "archival-video", "document",
           "screenshot", "map", "diagram", "typeset-card", "talking-head",
           "b-roll", "other"]
RELATIONS = ["literal", "evidence", "metaphor", "context", "reaction",
             "transition"]
FRAMINGS = ["extreme-wide", "wide", "medium", "close", "macro", "overhead",
            "surveillance", "screen-capture"]

SHOT_PROMPT = """You are studying ONE shot of a documentary to learn how its editor turns spoken words into pictures.

The narrator says over this shot:
"{line}"

Look at the frame and answer ONLY with JSON, no commentary:
{{"depicts": "<one concrete sentence: exactly what is on screen>",
 "device": <one of {devices}>,
 "relation": <one of {relations}>,
 "framing": <one of {framings}>,
 "subject": "<the main subject in 2-5 words>",
 "why": "<one sentence: why THIS picture serves THAT line>"}}

relation means how the picture answers the words:
- literal = it shows the very thing the line names
- evidence = it proves the claim (a document, a photo, a record)
- metaphor = it stands in for an abstract idea the line states
- context = the wider place, time or scale around the line
- reaction = the consequence or aftermath of what the line says
- transition = a beat between ideas, carrying no new information"""


def _shots(rep: Dict) -> List[Dict]:
    out = []
    for s in rep.get("shots") or []:
        if isinstance(s, (list, tuple)) and len(s) >= 2:
            out.append({"t0": float(s[0]), "t1": float(s[1]),
                        "trans": s[2] if len(s) > 2 else "cut",
                        "motion": (s[3] if len(s) > 3 else "static") or "static"})
    return out


def _line_for(segments: List[Dict], t0: float, t1: float) -> str:
    """Everything the narrator says while this shot is on screen."""
    bits = []
    for sg in segments:
        s, e = float(sg.get("s", 0)), float(sg.get("e", 0))
        if e > t0 and s < t1:                 # any overlap
            txt = (sg.get("text") or "").strip()
            if txt:
                bits.append(txt)
    return " ".join(bits).strip()


def _frame(video: Path, t: float, dst: Path) -> bool:
    subprocess.run([config.FFMPEG, "-y", "-ss", f"{t:.2f}", "-i", str(video),
                    "-frames:v", "1", "-vf", "scale=768:-2", str(dst)],
                   capture_output=True)
    return dst.exists() and dst.stat().st_size > 0


def _video_of(gid: str) -> Optional[Path]:
    d = GATHER_DIR / gid
    for name in ("video.mp4", "source.mp4"):
        if (d / name).exists():
            return d / name
    hits = [h for h in sorted(d.glob("*.mp4")) if not h.name.startswith("pack")]
    return hits[0] if hits else None


def analyze_shots(gid: str, max_shots: int = 140,
                  progress: Optional[Callable] = None,
                  model: Optional[str] = None) -> Dict:
    """PASS 1: pair every (sampled) shot with its narration and read both."""
    def note(m, f):
        if progress:
            progress(m, f)

    job_dir = GATHER_DIR / gid
    rep_f = job_dir / "report.json"
    if not rep_f.exists():
        raise ValueError(f"pack {gid} has no report.json")
    video = _video_of(gid)
    if not video:
        raise ValueError(f"pack {gid} kept no video (re-gather with keep_video)")
    if not vlm.available():
        raise RuntimeError("no local vision model (ollama serve + qwen2.5vl)")
    model = model or vlm.pick_model()

    rep = json.loads(rep_f.read_text(encoding="utf-8"))
    shots = _shots(rep)
    segments = rep.get("segments") or []
    if not shots:
        raise ValueError("no shots in report")

    # sample evenly across the runtime when a video has more shots than budget
    picks = shots
    if len(shots) > max_shots:
        step = len(shots) / max_shots
        picks = [shots[int(i * step)] for i in range(max_shots)]

    prompt_t = SHOT_PROMPT.replace("{devices}", json.dumps(DEVICES)) \
                          .replace("{relations}", json.dumps(RELATIONS)) \
                          .replace("{framings}", json.dumps(FRAMINGS))

    rows: List[Dict] = []
    t_start = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="compan_"))
    try:
        for i, sh in enumerate(picks):
            mid = sh["t0"] + (sh["t1"] - sh["t0"]) * 0.45
            line = _line_for(segments, sh["t0"], sh["t1"])
            if not line:
                line = "(no narration over this shot: music or silence)"
            f = tmp / f"s{i:04d}.jpg"
            if not _frame(video, mid, f):
                continue
            note(f"shot {i + 1}/{len(picks)} at {mid:.0f}s", i / len(picks))
            data = vlm.describe_json(f, prompt_t.replace("{line}", line[:400]),
                                     model=model)
            f.unlink(missing_ok=True)
            if not data:
                continue
            rows.append({
                "t0": round(sh["t0"], 2), "t1": round(sh["t1"], 2),
                "dur": round(sh["t1"] - sh["t0"], 2),
                "camera": sh["motion"], "transition": sh["trans"],
                "line": line,
                "depicts": data.get("depicts"), "device": data.get("device"),
                "relation": data.get("relation"), "framing": data.get("framing"),
                "subject": data.get("subject"), "why": data.get("why"),
            })
    finally:
        for f in tmp.glob("*"):
            f.unlink(missing_ok=True)
        tmp.rmdir()
        vlm.unload()

    out = {"gid": gid, "model": model, "shots_read": len(rows),
           "shots_total": len(shots),
           "seconds": round(time.time() - t_start, 1),
           "aggregate": aggregate(rows), "shots": rows}
    storage.write_json(job_dir / "composition.json", out)
    (job_dir / "composition.md").write_text(to_markdown(rep, out),
                                            encoding="utf-8")
    note("shot pass done", 1.0)
    return out


def aggregate(rows: List[Dict]) -> Dict:
    """The numbers a composer can actually follow."""
    from collections import Counter
    n = max(1, len(rows))
    rel = Counter(r.get("relation") or "?" for r in rows)
    dev = Counter(r.get("device") or "?" for r in rows)
    frm = Counter(r.get("framing") or "?" for r in rows)
    cam = Counter(r.get("camera") or "static" for r in rows)

    # THE LOOKUP THE COMPOSER NEEDS: what kind of line gets what kind of picture
    def kind_of(line: str) -> str:
        low = (line or "").lower()
        if re.search(r"\b(\d[\d,.]*\s*(million|billion|thousand|dollars|percent)|"
                     r"\$\d|\d{2,})\b", low):
            return "number/claim"
        if re.search(r"\b(19|20)\d{2}\b|o'clock|utc|january|february|march|april|"
                     r"may|june|july|august|september|october|november|december", low):
            return "date/time"
        if re.search(r"\b(he|she|they|his|her)\b", low) and re.search(
                r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", line or ""):
            return "person"
        if re.search(r"\b(said|says|told|called|asked|admits)\b", low):
            return "speech/quote"
        if re.search(r"\b(because|so|which meant|therefore|the reason)\b", low):
            return "explanation"
        if re.search(r"\b(is not|was never|no one|nobody|means|matters|truth)\b", low):
            return "abstraction"
        return "event/action"

    pairs: Dict[str, Counter] = {}
    for r in rows:
        k = kind_of(r.get("line") or "")
        pairs.setdefault(k, Counter())[f"{r.get('relation')}/{r.get('device')}"] += 1

    return {
        "relation_mix": {k: round(v / n, 3) for k, v in rel.most_common()},
        "device_mix": {k: round(v / n, 3) for k, v in dev.most_common()},
        "framing_mix": {k: round(v / n, 3) for k, v in frm.most_common()},
        "camera_mix": {k: round(v / n, 3) for k, v in cam.most_common()},
        "line_kind_to_picture": {
            k: [f"{c} ({n_} shots)" for c, n_ in v.most_common(3)]
            for k, v in pairs.items()},
    }


def to_markdown(rep: Dict, out: Dict) -> str:
    a = out["aggregate"]
    md = [f"# Composition analysis — {(rep.get('meta') or {}).get('title', out['gid'])}",
          "",
          f"{out['shots_read']} of {out['shots_total']} shots read with "
          f"{out['model']} in {out['seconds']}s.",
          "",
          "## How pictures answer words (relation mix)"]
    md += [f"- {k}: {v:.0%}" for k, v in a["relation_mix"].items()]
    md += ["", "## Devices"] + [f"- {k}: {v:.0%}" for k, v in a["device_mix"].items()]
    md += ["", "## Framing"] + [f"- {k}: {v:.0%}" for k, v in a["framing_mix"].items()]
    md += ["", "## THE COMPOSER LOOKUP — what each kind of line gets shown"]
    for k, v in a["line_kind_to_picture"].items():
        md += [f"- **{k}** -> " + "; ".join(v)]
    md += ["", "## Shot by shot (line -> picture -> why)", ""]
    for r in out["shots"]:
        md += [f"**{r['t0']:.0f}s** ({r['framing']}, {r['camera']}, {r['device']}, "
               f"{r['relation']})",
               f"- says: {(r['line'] or '')[:160]}",
               f"- shows: {r['depicts']}",
               f"- why: {r['why']}", ""]
    return "\n".join(md)


def submit(gid: str, max_shots: int = 140) -> str:
    """Queue pass 1 as a job (serializes with GPU work on the shared queue)."""
    def task(progress) -> Dict:
        return analyze_shots(gid, max_shots=max_shots, progress=progress)
    return jobs.submit("compose_analysis", task, pid=gid)


# ---------------------------------------------------------------- WHOLE VIDEO
def analyze_whole(gid: str) -> Dict:
    """Read the video AS A FILM, not as a bag of shots (user, 2026-07-14).

    Summing shots tells you the ingredients. A film has CURVES: the cut rate
    accelerates and holds, the media mix shifts act to act, the pictures start
    literal and turn metaphorical as the argument lands. This measures those
    movements over time — deterministically, from the pack — so the synthesis
    pass reasons about a SHAPE instead of an average.

    Everything here works with or without the per-shot VLM records; the curves
    come from the gatherer, the drifts come from composition.json when present.
    """
    job_dir = GATHER_DIR / gid
    rep = json.loads((job_dir / "report.json").read_text(encoding="utf-8"))
    shots = _shots(rep)
    segs = rep.get("segments") or []
    meta = rep.get("meta") or {}
    dur = float((rep.get("metrics") or {}).get("duration") or
                (shots[-1]["t1"] if shots else 0))
    if dur <= 0:
        raise ValueError("no duration")

    comp = storage.read_json(job_dir / "composition.json", {}) or {}
    rows = comp.get("shots") or []

    # --- curves, minute by minute -------------------------------------------
    n_min = max(1, int(dur // 60) + 1)
    cuts = [0] * n_min
    speech = [0.0] * n_min
    holds: List[Dict] = []
    for sh in shots:
        m = min(n_min - 1, int(sh["t0"] // 60))
        cuts[m] += 1
        if sh["t1"] - sh["t0"] >= 15:            # a deliberate long hold
            holds.append({"t": round(sh["t0"]), "dur": round(sh["t1"] - sh["t0"], 1)})
    for sg in segs:
        s, e = float(sg.get("s", 0)), float(sg.get("e", 0))
        m = min(n_min - 1, int(s // 60))
        speech[m] += max(0.0, e - s)
    speech_pct = [round(min(1.0, v / 60), 2) for v in speech]

    # --- how the picture strategy MOVES across the film -----------------------
    def slice_mix(lo: float, hi: float, key: str) -> Dict[str, float]:
        from collections import Counter
        sel = [r for r in rows if lo <= float(r.get("t0", 0)) < hi]
        if not sel:
            return {}
        c = Counter(r.get(key) or "?" for r in sel)
        return {k: round(v / len(sel), 2) for k, v in c.most_common(4)}

    thirds = []
    for i in range(3):
        lo, hi = dur * i / 3, dur * (i + 1) / 3
        thirds.append({
            "part": ["opening", "middle", "closing"][i],
            "from_t": round(lo), "to_t": round(hi),
            "cuts_per_min": round(sum(1 for s in shots if lo <= s["t0"] < hi)
                                  / max(1.0, (hi - lo) / 60), 1),
            "relation_mix": slice_mix(lo, hi, "relation"),
            "device_mix": slice_mix(lo, hi, "device"),
            "framing_mix": slice_mix(lo, hi, "framing"),
        })

    # --- the script as a script ----------------------------------------------
    full_text = " ".join((sg.get("text") or "").strip() for sg in segs)
    open_txt = " ".join((sg.get("text") or "") for sg in segs
                        if float(sg.get("s", 0)) < 60).strip()
    close_txt = " ".join((sg.get("text") or "") for sg in segs
                         if float(sg.get("s", 0)) > dur - 60).strip()
    # signposted turns: the lines that move the story in time or place
    turns = [{"t": round(float(sg.get("s", 0))), "line": (sg.get("text") or "").strip()}
             for sg in segs
             if re.match(r"^\s*(back in|a year earlier|meanwhile|by \d{4}|"
                         r"in (19|20)\d{2}|on the \d+|\d+ (days?|weeks?|months?|"
                         r"years?) later|but first|here is how|this is)",
                         (sg.get("text") or "").strip(), re.I)]

    out = {
        "gid": gid, "title": meta.get("title"), "duration": round(dur),
        "curves": {"cuts_per_min_by_minute": cuts,
                   "speech_share_by_minute": speech_pct},
        "long_holds": sorted(holds, key=lambda h: -h["dur"])[:8],
        "arc": thirds,
        "turns": turns[:14],
        "opening_60s": open_txt[:900],
        "closing_60s": close_txt[:900],
        "words": len(full_text.split()),
        "shot_records": len(rows),
    }
    storage.write_json(job_dir / "whole.json", out)
    return out


# ---------------------------------------------------------------- PASS 2
SYNTHESIS_PROMPT = """Below is the shot-by-shot record of a documentary: for every shot, what the narrator SAID, what the editor SHOWED, how the picture relates to the words, and the device and framing used.

You are ALSO given the whole-film measurements: how the cut rate rises and falls minute by minute, where the editor holds a shot for a long time, how the picture strategy shifts between the opening, middle and closing thirds, and the signposted story turns.

Read it as ONE FILM. Do not analyze scenes in isolation and do not summarise the plot.

Read it as a whole. Do not summarise the story — study the ARCHITECTURE: how the pictures are built out of the words, how shots connect into acts, what is set up and paid off later, what the editor does at the open and the close, and what is implied between the lines.

Return STRICT JSON:
{"acts": [{"name": "", "from_t": 0, "to_t": 0, "function": ""}],
 "opening_strategy": "how the first 60 seconds hooks and orients, in picture terms",
 "closing_strategy": "how the last 60 seconds lands",
 "recurring_spaces": ["places the video returns to, and why"],
 "recurring_characters": ["figures that reappear, and how they stay recognisable"],
 "callbacks": [{"setup_t": 0, "payoff_t": 0, "what": ""}],
 "rhythm": "how literal / evidence / metaphor shots alternate, and the pace of it",
 "reading_between_the_lines": ["what the editor is doing that is never stated out loud"],
 "rules_for_composer": ["direct, actionable instructions for someone writing image prompts for a NEW video in this style. Be concrete. Name the device to use for each kind of line."]}

THE RECORD:
"""


def synthesis_input(gid: str) -> Dict:
    """The pass-2 payload: prompt + the compact ordered record.

    AI-AGNOSTIC on purpose (SKILL_PACKS contract): any model — Claude, the
    local LLM, anything else — can be handed this and produce the architecture.
    """
    data = storage.read_json(GATHER_DIR / gid / "composition.json", {}) or {}
    rows = data.get("shots") or []
    if not rows:
        raise ValueError(f"pack {gid} has no composition.json — run pass 1 first")
    record = "\n".join(
        f"[{r['t0']:.0f}s {r['framing']}/{r['camera']}/{r['device']}/{r['relation']}] "
        f"SAYS: {(r['line'] or '')[:120]} | SHOWS: {r['depicts']}"
        for r in rows)
    return {"gid": gid, "prompt": SYNTHESIS_PROMPT, "record": record,
            "aggregate": data.get("aggregate"), "shots": len(rows)}


def synthesize_local(gid: str, model: str = "qwen3:8b") -> Optional[Dict]:
    """Run pass 2 through the local text LLM (fallback when no Claude is
    driving). Writes architecture.json next to the pack."""
    import urllib.request
    payload = synthesis_input(gid)
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user",
                      "content": payload["prompt"] + payload["record"][:24000]}],
        "stream": False, "think": False, "keep_alive": 0,
        "options": {"temperature": 0.2, "num_ctx": 32768, "num_predict": 3000},
    }).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        txt = ((json.loads(r.read()).get("message") or {}).get("content") or "")
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m:
        return None
    try:
        arch = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    storage.write_json(GATHER_DIR / gid / "architecture.json", arch)
    return arch
