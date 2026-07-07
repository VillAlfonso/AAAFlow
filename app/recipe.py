"""The RECIPE CARD — exact ingredients + measurements of one video.

The user's mental model (2026-07-05): he's a chef, the pipeline stages are
ingredients. Every video therefore gets a legible recipe: what went in (script
stats, direction card, voice + humanize, art direction, edit grammar counts,
score plan, packaging, research sources) and in what measure. Aggregated live
from project.json — nothing here is a second source of truth.

`GET /api/projects/{pid}/recipe` returns the JSON; the packager writes the
human-readable `video/recipe.md` next to the upload kit.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from . import projects


def _wc(t: str) -> int:
    return len((t or "").split())


def build(pid: str) -> Dict:
    p = projects.get_project(pid)
    if not p:
        raise ValueError("project not found")
    scenes = p.get("scenes", [])
    video = p.get("video", {}) or {}
    settings = p.get("settings", {}) or {}
    narr = p.get("narration") or {}
    plan = p.get("audio_plan") or {}
    seo = p.get("seo") or {}
    research = p.get("research") or {}
    tl = p.get("timeline") or {}
    render = (p.get("renders") or [{}])[0]

    words = sum(_wc(s.get("narration")) for s in scenes)
    transitions = Counter((s.get("transition") or "—").lower() for s in scenes)
    cues = Counter((s.get("audio_cue") or "").lower() for s in scenes if s.get("audio_cue"))
    fx = Counter(f for s in scenes for f in (s.get("fx") or []))
    emphasized = [s for s in scenes if s.get("emphasis")]
    heroes = sum(1 for s in scenes if (s.get("motion_type") or "").strip())
    locked = sum(1 for s in scenes if s.get("image_locked"))
    card = video.get("direction_card") or {}

    return {
        "title": video.get("title") or p.get("name"),
        "channel": p.get("channel"),
        "duration_sec": round(float(tl.get("total_dur") or 0), 1),
        "direction_card": {k: card.get(k) for k in
                           ("id", "hook_style", "ending", "why") if card.get(k)},
        "script": {
            "scenes": len(scenes), "words": words,
            "words_per_scene": round(words / max(len(scenes), 1), 1),
            "hook": (scenes[0].get("narration") if scenes else ""),
            "cast": [b.get("name") for b in (p.get("character_bible") or [])
                     if b.get("name")],
        },
        "voice": {
            "narrator": narr.get("voice"),
            "humanize": narr.get("humanize"),
            "take_sec": narr.get("dur"),
            "qa_ok": ((narr.get("qa") or {}).get("ok")),
            "instruct": (settings.get("voice") or {}).get("instruct"),
        },
        "look": {
            "style": (video.get("global_style_suffix") or "")[:160],
            "image_model": (settings.get("image") or {}).get("model"),
            "preset": (settings.get("assemble") or {}).get("preset"),
            "receipt_stills": locked,
        },
        "edit": {
            "transitions": dict(transitions.most_common(8)),
            "scene_fx": dict(fx),
            "emphasis_hits": len(emphasized),
            "emphasis_words": [str((s.get("emphasis") or [""])[0])
                               for s in emphasized[:10]],
            "hero_scenes": heroes,
        },
        "sound": {
            "mood": plan.get("mood"),
            "bed": (plan.get("bed") or {}).get("source"),
            "bed_title": (plan.get("bed") or {}).get("title"),
            "sfx_cues": dict(cues.most_common(8)),
            "music_vibe": settings.get("music_vibe"),
        },
        "package": {
            "seo_title": (seo.get("titles") or [None])[0],
            "thumb_template": seo.get("thumb_template"),
            "thumb_mood": seo.get("thumb_mood"),
            "tags_lead": (seo.get("tags") or [])[:8],
        },
        "research": {
            "sources": [s.get("title") or s.get("url")
                        for s in (research.get("sources") or [])
                        if isinstance(s, dict)],
            "facts": len(research.get("facts") or []),
        },
        "render": {
            "file": render.get("file"), "duration": render.get("duration"),
            "size": f"{render.get('width')}×{render.get('height')}",
            "wan_clips": render.get("with_videos"),
            "sfx_placed": render.get("with_sfx"),
        },
    }


def write_md(pid: str) -> Optional[str]:
    """Human-readable recipe next to the upload kit. Never raises."""
    try:
        r = build(pid)
        L: List[str] = [f"# 🧾 Recipe — {r['title']}", ""]
        card = r["direction_card"]
        if card:
            L += [f"**Direction card:** {card.get('id')} — hook: "
                  f"{card.get('hook_style')} · ending: {card.get('ending')}", ""]
        s = r["script"]
        L += [f"**Script** · {s['scenes']} scenes · {s['words']} words "
              f"({s['words_per_scene']}/scene) · cast: "
              f"{', '.join(s['cast']) or '—'}",
              f"**Hook** · {s['hook']}",
              f"**Voice** · {r['voice']['narrator']} · humanize "
              f"{r['voice']['humanize'] or 'off'} · QA "
              f"{'ok' if r['voice']['qa_ok'] else 'CHECK'}",
              f"**Look** · {r['look']['image_model']} · preset "
              f"{r['look']['preset'] or 'cinematic'} · {r['look']['style']}…",
              f"**Edit** · cuts: " + ", ".join(
                  f"{k}×{v}" for k, v in r["edit"]["transitions"].items()) +
              f" · {r['edit']['emphasis_hits']} emphasis hits · "
              f"{r['edit']['hero_scenes']} hero scenes · fx {r['edit']['scene_fx'] or '—'}",
              f"**Sound** · mood {r['sound']['mood']} · bed {r['sound']['bed']}"
              + (f" ({r['sound']['bed_title']})" if r['sound']['bed_title'] else "")
              + " · cues: " + (", ".join(
                  f"{k}×{v}" for k, v in r["sound"]["sfx_cues"].items()) or "—"),
              f"**Package** · “{r['package']['seo_title']}” · thumb "
              f"{r['package']['thumb_template']} ({r['package']['thumb_mood']}) · "
              f"tags: {', '.join(r['package']['tags_lead'])}",
              ]
        if r["research"]["sources"]:
            L += ["**Sources** · " + " · ".join(r["research"]["sources"][:5])]
        if r["render"]["file"]:
            L += [f"**Render** · {r['render']['file']} · "
                  f"{r['render']['duration']}s · {r['render']['size']} · "
                  f"{r['render']['wan_clips']} Wan clips · "
                  f"{r['render']['sfx_placed']} SFX"]
        out = projects.project_dir(pid) / "video" / "recipe.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n\n".join(L), encoding="utf-8")
        return "video/recipe.md"
    except Exception:  # noqa: BLE001
        return None
