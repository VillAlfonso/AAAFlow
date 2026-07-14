"""Deterministic direction — make a bare storyboard fully directed.

The intelligence a video needs to LOOK edited (transition variety, stinger
placement, hero-scene selection, shot variety, the no-text rule, TTS-safe
punctuation) lives HERE — the WHICH-effect-WHEN choices come from the editable
``app/grammar.py`` dictionary (``data/effects_dictionary.json``), not whichever
LLM wrote the storyboard.
A minimal storyboard — title + scenes with narration and an image subject —
comes out the other side with every directing field filled. Fields the author
DID provide are never overwritten, so a strong model (or a human) can still
out-direct the defaults; a weak model simply can't produce an undirected video.

Runs automatically on project import; also exposed as POST /api/storyboard/lint
(report + optional fixed copy).
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from . import grammar, sfx
from .scenes import estimate_duration

HOOK_SECONDS = 30.0          # the window that must carry the densest editing

# Transition rotations, shot variety and keyword→cue mappings all live in the
# editable grammar dictionary now (app/grammar.py -> data/effects_dictionary.json)
# so "when to use which effect" is one JSON, shared with the audio scorer.


def _word_count(t: str) -> int:
    return len(re.findall(r"\w+", t or ""))


def _pick_cue(text: str) -> str:
    return grammar.pick_cue(text)


_STOPW = set("a an the of in on at to for with and or but as is was were are be "
             "been his her hers their its this that these those it he she they "
             "them him from by into over under after before then than when "
             "while who what where why how not no had has have did does do "
             "will would could should there here about just very".split())


def _content_words(t: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z'-]+", (t or "").lower())
            if w not in _STOPW and len(w) > 2}


def _stem(w: str) -> str:
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def _visuals_match(narr: str, prompt: str) -> bool:
    """Does the visual share ANY subject with the line? Exact word, same stem
    (entries/entry), or compound containment (log/logbook) all count — this is
    a slideshow-drift heuristic, not a grammar test."""
    A, B = _content_words(narr), _content_words(prompt)
    if A & B:
        return True
    As, Bs = {_stem(w) for w in A}, {_stem(w) for w in B}
    if As & Bs:
        return True
    for x in As:
        for y in Bs:
            lo, hi = (x, y) if len(x) <= len(y) else (y, x)
            # containment anywhere (phone/telephone, house/farmhouse) — a
            # drift HEURISTIC, so a rare false pass beats constant false alarms
            if len(lo) >= 4 and lo in hi:
                return True
            if len(lo) == 3 and hi.startswith(lo) and len(hi) >= 6:
                return True
    return False


def _subject_of(narr: str, n: int = 7) -> str:
    """The line's concrete subject — its first content words, in order."""
    toks = [w for w in re.findall(r"[A-Za-z][\w'-]*", narr or "")
            if w.lower() not in _STOPW][:n]
    return " ".join(toks)


# --- word-level emphasis (writer *markup* wins; else grammar detectors) -------
_EMPH_MARK_RE = re.compile(r"\*([^*\n]{1,42}?)\*")
_NUM_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|thousand))?"
    r"|\b\d[\d,]*(?:\.\d+)?\s*(?:million|billion|thousand|percent|years?|days?|"
    r"nights?|hours?|minutes?|men|women|children|people|bodies|victims|times|"
    r"miles|feet|tons?|keepers?|hikers?)\b"
    r"|\b(?:three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|"
    r"thirty|forty|fifty|hundred|thousand|million|billion)\b"
    r"|\b\d[\d,]{0,7}\b", re.I)


def _pull_markup(narr: str):
    """Extract *marked* phrases; return (tts-clean text, phrases)."""
    phrases = [m.strip() for m in _EMPH_MARK_RE.findall(narr) if m.strip()]
    clean = _EMPH_MARK_RE.sub(lambda m: m.group(1), narr)
    return clean.replace("*", ""), phrases


def _auto_emphasis(narr: str, cfg: Dict) -> List[str]:
    """The one phrase a human editor would punch: a number/amount first, else
    the strongest absolute word — preferring late in the line, where it lands."""
    if cfg.get("detect_numbers", True):
        m = list(_NUM_RE.finditer(narr or ""))
        if m:
            return [m[-1].group(0).strip()]
    low = (narr or "").lower()
    best = None
    for w in (cfg.get("detect_words") or []):
        i = low.rfind(w)
        if i < 0 or (best and i <= best[0]):
            continue
        j = i + len(w)
        if (i == 0 or not low[i - 1].isalnum()) and (j >= len(low) or not low[j].isalnum()):
            best = (i, narr[i:j])
    return [best[1]] if best else []


# --- assisted mode (small-model authoring, e.g. Haiku) -----------------------
# In "assisted" mode the director may REWRITE weak structure, not just fill
# gaps: an overlong cold open gets trimmed to a hard hook, rambling scenes are
# split into extra cuts. Runs before the fill pass so new scenes get directed
# like any other. Pro mode never touches author text beyond punctuation.
_SENT_RE = re.compile(r"(?<=[.!?…])\s+")


def _trim_hook(text: str, max_words: int = 12):
    """Shorten an overlong opening line at a sentence/clause boundary."""
    if _word_count(text) <= max_words + 2:
        return None
    first = _SENT_RE.split(text.strip())[0].strip()
    if 3 <= _word_count(first) <= max_words + 2:
        return first if first[-1:] in ".!?…" else first + "."
    cut = None
    for m in re.finditer(r"[,;:—–-]", text):
        if _word_count(text[: m.start()]) <= max_words:
            cut = m.start()
        else:
            break
    if cut and _word_count(text[:cut]) >= 4:
        return text[:cut].rstrip() + "."
    return None


def _split_scene(s: Dict):
    """Split a long multi-sentence scene into two cuts near its word midpoint."""
    narr = (s.get("narration") or "").strip()
    if _word_count(narr) <= 26:
        return None
    sents = [x.strip() for x in _SENT_RE.split(narr) if x.strip()]
    if len(sents) < 2:
        return None
    total, acc, best_i, best_gap = _word_count(narr), 0, None, 1e9
    for i in range(len(sents) - 1):
        acc += _word_count(sents[i])
        gap = abs(acc - total / 2)
        if gap < best_gap:
            best_gap, best_i = gap, i
    a = " ".join(sents[: best_i + 1])
    b = " ".join(sents[best_i + 1:])
    if _word_count(a) < 6 or _word_count(b) < 6:
        return None
    s1, s2 = dict(s), dict(s)
    s1["narration"], s2["narration"] = a, b
    ip = (s.get("image_prompt") or "").strip()
    if ip:
        s2["image_prompt"] = ip + " — a different moment, alternate angle and composition"
    # scene B is a fresh cut: clear directing fields so the fill pass re-picks
    for k in ("transition", "shot", "audio_cue", "motion_type", "motion_prompt"):
        s2[k] = ""
    for sc in (s1, s2):
        for k in ("start_sec", "end_sec", "duration_sec"):
            sc.pop(k, None)               # re-pace both halves from narration
    return s1, s2


def _assist(scenes: List[Dict], video: Dict, fixes: List[str]) -> List[Dict]:
    if scenes:
        trimmed = _trim_hook(scenes[0].get("narration") or "")
        if trimmed:
            scenes[0]["narration"] = trimmed
            fixes.append(f"assist: cold open trimmed to a hard hook — '{trimmed}'")
    out: List[Dict] = []
    splits = 0
    for s in scenes:
        pair = _split_scene(s) if splits < 8 else None
        if pair:
            splits += 1
            fixes.append(f"scene {s.get('id')}: long narration split into two cuts (assist)")
            out.extend(pair)
        else:
            out.append(s)
    if splits:
        remap: Dict = {}
        for i, s in enumerate(out):
            old = s.get("id")
            if old is not None and old not in remap:
                remap[old] = i + 1
            s["id"] = i + 1
        if video.get("thumbnail_scene") in remap:
            video["thumbnail_scene"] = remap[video["thumbnail_scene"]]
        fixes.append(f"assist: scenes renumbered 1..{len(out)} after {splits} split(s)")
    return out


def direct(raw: Dict, *, default_style: str | None = None,
           strict: bool = False, coverage: str = "heroes") -> Tuple[Dict, Dict]:
    """Fill every empty directing field; return (storyboard, report).

    ``default_style`` (usually the project's channel art direction) wins over
    the built-in flat-cartoon fallback when the storyboard declares no style.
    ``strict`` enables assisted mode: structural rewrites for weak-model
    scripts (hook trimming, long-scene splitting).
    ``coverage`` decides which scenes get flagged for Wan animation:
    "heroes" (budgeted — every scene still cuts to a fresh moving visual via
    parallax/Ken Burns), "all" (every scene gets a real clip; ~3.5 min GPU per
    scene at balanced), or "none".
    """
    sb = dict(raw or {})
    video = dict(sb.get("video") or {})
    scenes = [dict(s) for s in (sb.get("scenes") or [])]
    fixes: List[str] = []
    warnings: List[str] = []

    if not (video.get("global_style_suffix") or "").strip():
        if (default_style or "").strip():
            video["global_style_suffix"] = default_style.strip()
            fixes.append("video: empty global_style_suffix -> channel art direction")
        else:
            from . import config
            video["global_style_suffix"] = config.KREA2_STYLE
            fixes.append("video: empty global_style_suffix -> flat-cartoon preset")

    if strict:
        scenes = _assist(scenes, video, fixes)

    # cumulative planned time decides which scenes sit inside the hook window
    t = 0.0
    hook_idx: List[int] = []
    starts: List[float] = []
    for i, s in enumerate(scenes):
        starts.append(t)
        if t < HOOK_SECONDS:
            hook_idx.append(i)
        t += estimate_duration(s.get("narration") or "")

    # draw the direction card (anti-factory: same rules, different skeleton).
    # Author-set cards are kept; the pick is seeded so re-linting is stable.
    cards = grammar.direction_cards()
    if cards and not video.get("direction_card"):
        seed = sum(ord(c) for c in (video.get("title") or "")) + len(scenes)
        video["direction_card"] = dict(cards[seed % len(cards)])
        fixes.append(f"video: direction card -> {video['direction_card'].get('id')}")
    card = video.get("direction_card") or {}
    t_off = int(card.get("transition_offset", 0) or 0)

    bible = [b for b in (sb.get("character_bible") or [])
             if (b.get("name") or "").strip()]
    bible_names = [b["name"].strip() for b in bible]
    e_cfg = grammar.emphasis_cfg()
    e_max = max(1, int(e_cfg.get("max_per_scene", 1)))
    last_emph = -9          # auto-emphasis at most every other scene
    last_chip_year, last_chip_i = "", -9      # date chips: new years only
    g_cfg = grammar.dictionary().get("sfx_gating") or {}
    cue_gap = max(0, int(g_cfg.get("min_gap_scenes", 2)))
    last_cue_i = -9         # stinger spacing (see the audio_cue block)
    drift: List[int] = []   # scenes whose visual ignores the narration subject

    last_transition = ""
    # animation coverage: "all" = a real clip on every scene (viewer-retention
    # maximalist — costly), "heroes" = budgeted (dense for short videos, grows
    # slowly for long ones), "none" = parallax/Ken Burns carry all motion.
    ns = len(scenes)
    if coverage == "all":
        heroes = set(range(ns))
    elif coverage == "none":
        heroes = set()
    else:
        hero_budget = (max(3, min(10, ns // 4)) if ns <= 60
                       else min(16, 10 + (ns - 60) // 30))
        # hero scenes get motion: scene 1, then the longest scenes spread out
        by_len = sorted(range(ns),
                        key=lambda i: -_word_count(scenes[i].get("narration") or ""))
        heroes = {0} | set(by_len[: hero_budget - 1])

    for i, s in enumerate(scenes):
        sid = s.get("id", i + 1)
        narr = (s.get("narration") or "").strip()

        # writer *emphasis* markup: pull the phrases out, keep the TTS text clean
        if "*" in narr:
            clean, marked = _pull_markup(narr)
            s["narration"] = narr = clean.strip()
            if marked and not s.get("emphasis"):
                s["emphasis"] = marked[:e_max]
                last_emph = i
            fixes.append(f"scene {sid}: emphasis markup -> "
                         f"{', '.join(marked) if marked else 'stripped'}")

        # No em dashes in narration (user rule, 2026-07-10): they read as an
        # AI tell and the TTS stumbles on them. A trailing dash becomes a full
        # stop; an internal one becomes the comma a narrator would breathe on.
        if "—" in narr or "–" in narr:
            fixed = re.sub(r"\s*[—–]\s*([.!?])", r"\1", narr)     # "accident —." -> "accident."
            fixed = re.sub(r"\s*[—–]\s*$", ".", fixed)             # trailing dash -> period
            fixed = re.sub(r"\s*[—–]\s*", ", ", fixed)             # internal -> comma
            fixed = re.sub(r",\s*([.!?])", r"\1", fixed)
            if fixed != narr:
                s["narration"] = narr = fixed
                fixes.append(f"scene {sid}: em dash in narration -> comma/period")

        # TTS-safe punctuation: trailing commas invite hallucinated continuations
        if narr.endswith(","):
            s["narration"] = narr[:-1] + "."
            fixes.append(f"scene {sid}: narration ended with ',' -> '.'")
        elif narr and narr[-1] not in ".!?…\"'":
            s["narration"] = narr + "."
            fixes.append(f"scene {sid}: added terminal period to narration")

        # the no-burned-text rule is absolute
        if (s.get("on_screen_text") or "").strip():
            s["on_screen_text"] = ""
            fixes.append(f"scene {sid}: cleared on_screen_text (never rendered)")

        if not (s.get("image_prompt") or "").strip():
            base = (s.get("visual") or s.get("narration") or "").strip()
            if base:
                s["image_prompt"] = f"Clear single-subject illustration of: {base}"
                warnings.append(f"scene {sid}: image_prompt synthesized from "
                                f"narration — a real prompt would look better")

        # STORY-FIRST VISUALS: the picture must show what the line says — a
        # visual sharing zero content words with its narration is slideshow
        # filler, not storytelling. Assisted mode repairs it; pro mode warns.
        ip = (s.get("image_prompt") or "").strip()
        if ip and narr and not _visuals_match(narr, ip):
            subj = _subject_of(narr)
            if strict and subj:
                s["image_prompt"] = f"{ip} — clearly showing {subj}"
                fixes.append(f"scene {sid}: visual didn't depict the line — "
                             f"anchored to '{subj}'")
            else:
                drift.append(sid)

        # recurring-cast continuity: if a bible character is named in the line
        # but the scene doesn't list them, list them (fills a gap — the prompt
        # builder then appends their fixed look, keeping the cast on-model).
        if bible_names and not s.get("characters"):
            hit = [n for n in bible_names
                   if re.search(rf"\b{re.escape(n.split()[0])}\b",
                                f"{narr} {ip}", re.I)]
            if hit:
                s["characters"] = hit
                fixes.append(f"scene {sid}: characters -> {', '.join(hit)}")

        # Effects key off what is SPOKEN, never off the picture (user,
        # 2026-07-10: "don't randomly put sound effects where they don't
        # belong") - a burning-house image_prompt must not smash-cut a calm
        # line. The beat comes from the narration alone.
        beat = grammar.beat_of(narr)
        if not (s.get("transition") or "").strip():
            # A detected story beat picks its signature cut (reveal→flash,
            # impact→smash…); otherwise rotate the hook/body set, never repeating.
            pick = grammar.transition_for_beat(beat) if beat else ""
            if not pick or pick == last_transition:
                cycle = grammar.transitions(i in hook_idx)
                pick = cycle[(i + t_off) % len(cycle)]
                if pick == last_transition:
                    pick = cycle[(i + t_off + 1) % len(cycle)]
            s["transition"] = pick
            fixes.append(f"scene {sid}: transition -> {pick}")
        last_transition = s["transition"]

        if not (s.get("audio_cue") or "").strip():
            # spacing rule: a stinger needs air around it or it reads random;
            # dictionary "sfx_gating".min_gap_scenes overrides (default 2)
            cue = _pick_cue(narr) if i - last_cue_i >= cue_gap else ""
            if not cue and i in hook_idx and i > 0 and i - last_cue_i >= 2:
                cue = "quick whoosh"        # hook cuts still carry energy
            if cue:
                s["audio_cue"] = cue
                last_cue_i = i
                fixes.append(f"scene {sid}: audio_cue -> {cue}")
        else:
            last_cue_i = i                  # an author cue spaces the next auto one

        if not (s.get("shot") or "").strip():
            shots = grammar.shots()
            s["shot"] = shots[i % len(shots)]

        if not (s.get("motion_type") or "").strip() and i in heroes:
            s["motion_type"] = "ambient"
            fixes.append(f"scene {sid}: flagged as hero (ambient motion)")

        # whole-scene FX on the beats that matter (grammar scene_fx)
        if beat and not s.get("fx"):
            if (i in heroes) or not grammar.scene_fx_hero_only():
                fxn = grammar.scene_fx_for(beat)
                if fxn:
                    s["fx"] = [fxn]
                    fixes.append(f"scene {sid}: scene fx -> {fxn} ({beat} beat)")

        # DATE CHIP: a mentioned year/date is the perfect transition moment
        # (user, 2026-07-05) — stamp a small typeset chip (assembler adds a
        # click). Only on a NEW year, never two scenes running.
        if not (s.get("date_chip") or "").strip():
            ym = re.search(r"\b(1[6-9]\d\d|20[0-2]\d)\b", narr)
            if ym and ym.group(1) != last_chip_year and i - last_chip_i >= 2:
                md = re.search(r"\b(January|February|March|April|May|June|July|"
                               r"August|September|October|November|December)"
                               r"\s+\d{1,2}(?:\w{2})?,?\s*" + ym.group(1), narr)
                s["date_chip"] = md.group(0).replace(",", ", ").replace("  ", " ") \
                    if md else ym.group(1)
                last_chip_year, last_chip_i = ym.group(1), i
                fixes.append(f"scene {sid}: date chip -> {s['date_chip']}")

        # word-level emphasis: author's field wins; else detect ONE phrase —
        # and never two auto-punches on back-to-back scenes (metronome guard).
        if s.get("emphasis"):
            s["emphasis"] = [str(x).strip() for x in s["emphasis"]][:e_max]
        elif i - last_emph >= 2:
            auto = _auto_emphasis(narr, e_cfg)
            if auto:
                s["emphasis"] = auto[:e_max]
                last_emph = i

    # --- lint-only observations ---------------------------------------------
    if scenes:
        first = _word_count(scenes[0].get("narration") or "")
        if first > 14:
            warnings.append(f"hook: scene 1 narration is {first} words — open "
                            f"with <= 12 for a hard hook")
        hook_words = sum(_word_count(scenes[i].get("narration") or "")
                         for i in hook_idx)
        if hook_idx and hook_words / max(len(hook_idx), 1) > 16:
            warnings.append("hook: first-30s scenes average > 16 words — cut "
                            "faster (aim 6-12 words/scene)")
        total = sum(_word_count(s.get("narration") or "") for s in scenes)
        if total:
            est = total / 2.6 + len(scenes) * 0.4
            stats = {"scenes": len(scenes), "words": total,
                     "est_runtime_sec": round(est, 1),
                     "hook_scenes": len(hook_idx)}
            if total > 650:
                warnings.append(f"long script ({total} words): one-take TTS can "
                                f"drift past ~5 min — spot-check the QA transcript "
                                f"extra carefully (chapter takes are the next fix "
                                f"if it drifts)")
        else:
            stats = {"scenes": len(scenes), "words": 0}
            warnings.append("no narration anywhere — nothing to voice")
    else:
        stats = {"scenes": 0}
        warnings.append("storyboard has no scenes")

    # unknown audio cues (won't match the library OR the synth fallback)
    for s in scenes:
        cue = (s.get("audio_cue") or "").strip()
        if cue and sfx.classify(cue) is None and sfx._match_library(cue) is None:
            warnings.append(f"scene {s.get('id')}: audio_cue '{cue}' matches no "
                            f"library tag or synth — it will be silent")

    # retention: a long stretch on one motionless image is where viewers leave
    for s in scenes:
        est = estimate_duration(s.get("narration") or "")
        if est > 18.0 and (s.get("motion_type") or "") not in ("ambient", "transform"):
            warnings.append(f"scene {s.get('id')}: ~{est:.0f}s on a single still "
                            f"— split the narration or flag motion_type ambient")

    # story-first summary: visuals that ignore the narration are "cool
    # slideshow", not storytelling — the #1 way a video loses its viewer.
    if drift:
        head = ", ".join(str(x) for x in drift[:8])
        warnings.append(f"visuals drift from the narration in {len(drift)}/"
                        f"{len(scenes)} scenes ({head}{'…' if len(drift) > 8 else ''}) "
                        f"— the picture must SHOW what the line says, or the "
                        f"viewer can't follow the story with the sound off")

    # a recurring name with no character_bible entry = a cast member whose
    # face changes every scene (continuity is what makes visuals track a story)
    if not bible_names and scenes:
        from collections import Counter as _Counter
        toks: List[str] = []
        for line in (sc.get("narration") or "" for sc in scenes):
            for sent in _SENT_RE.split(line):
                ws = sent.strip().split()
                toks += [w.strip(".,;:!?…\"'—–") for w in ws[1:]]
        cnt = _Counter(w for w in toks
                       if w[:1].isupper() and w[1:2].islower() and len(w) > 2)
        top = sorted([n for n, c in cnt.items() if c >= 3])[:3]
        if top:
            warnings.append(f"recurring name(s) {', '.join(top)} have no "
                            f"character_bible entry — add one (fixed look) so "
                            f"the cast stays visually consistent across scenes")

    sb["video"] = video
    sb["scenes"] = scenes

    # OVERLAY DIRECTOR (2026-07-14): decide every typeset moment from the
    # narration itself — date/location stamps, name tags, chapter cards.
    # Wan renders content and never text; Remotion renders these.
    try:
        from . import overlays as _ov
        plan = _ov.plan(sb)
        if plan:
            stats["overlays"] = len(plan)
            fixes.append(f"overlay director: {len(plan)} typeset moment(s) "
                         + ", ".join(sorted({p['detector'] for p in plan})))
    except Exception as exc:  # noqa: BLE001 — never block an import
        warnings.append(f"overlay director skipped ({type(exc).__name__})")

    stats["emphasized"] = sum(1 for s in scenes if s.get("emphasis"))
    stats["scene_fx"] = sum(1 for s in scenes if s.get("fx"))
    report = {"fixes": fixes, "warnings": warnings, "stats": stats,
              "mode": "assisted" if strict else "standard"}
    return sb, report
