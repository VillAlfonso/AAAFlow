"""Channel Roulette — press one button, get a whole new channel to keep or spin away.

One roll = a local LLM (Ollama if reachable, else the in-process Qwen3-4B —
the same engines as the script writer) invents a complete channel concept:
name, niche, tagline, audience, repeatable video formats, writing brief, a
full krea2 art direction, a narrator voice direction, a music vibe, a topic
bank, five example video titles and an SEO pool. Then the brandkit's FIXED
krea2 node graph renders the concept's identity stills (profile · banner ·
thumbnail · host · ambiance) so you can SEE the channel before it exists.

Rolls live in ``data/roulette/<rid>/`` — concept.json + the PNGs + the saved
node graph (``graph.json``). Every PNG embeds the workflow: drag one into
ComfyUI at 127.0.0.1:8188 to remix the exact nodes and re-queue with new
seeds. Accepting a roll creates the REAL channel folder with these defaults
and the stills become its brand kit; rerolling just rolls again (~2 min GPU).

The LLM receives "inspiration dice" (random subject × aesthetic × tone drawn
in Python) so repeated rolls actually differ — same-prompt LLM calls repeat
themselves otherwise. With no LLM reachable at all, a hand-written fallback
concept keyed off the same dice is used, so the button never dies.

Every concept is constrained to what this pipeline automates WELL: narrated
documentary formats over flat illustrated 2D art (krea2's strength + Wan's
easiest motion), one narrator, no on-screen text, no photorealistic humans.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from . import channels, config, jobs, storage, writer
from .brandkit import build_graph, publish_graph_to_comfy
from .comfy_engine import comfy_engine

ROULETTE_DIR = config.DATA_DIR / "roulette"

# The identity subset a roll renders (fast: 5 branches ≈ half the full kit).
_ROLL_SLOTS = ["profile", "banner", "thumbnail", "host", "ambiance_wide"]

_VOICES = ("Ryan", "Aiden")               # native-English Qwen3-TTS presets
_THUMB_TEMPLATES = ("spotlight", "case-file", "reveal", "split", "bar")

# --- inspiration dice ---------------------------------------------------------
# Subjects are niches a one-narrator, still-image-led documentary automates well.
_SUBJECTS = [
    "unsolved disappearances", "cursed and haunted objects", "great cons and swindles",
    "engineering disasters", "deep sea discoveries", "space missions that went wrong",
    "forgotten empires and lost cities", "financial collapses and manias",
    "heists that almost worked", "medical mysteries of history",
    "expeditions that never returned", "secret Cold War projects",
    "ancient machines and inventions", "internet mysteries and lost media",
    "natural disasters that changed history", "black markets and smuggling routes",
    "codes and ciphers nobody cracked", "obsessions that ruined brilliant people",
    "borders, maps and territorial oddities", "food history scandals",
    "trains, ships and vanished vehicles", "art forgeries and stolen masterpieces",
]
_AESTHETICS = [
    "minimal stick-figure diagram art on warm paper, confident marker linework",
    "blueprint / technical-drawing style, white line art on deep drafting blue",
    "vintage pulp-comic halftone, bold ink and two-color print",
    "paper-cutout diorama with layered card stock and soft drop shadows",
    "art-deco travel-poster style, geometric shapes and gold foil accents",
    "woodcut / linocut print, heavy carved lines and one spot color",
    "chalk on slate blackboard, dusty white lines with colored chalk accents",
    "ukiyo-e woodblock style, flat washes and pattern waves",
    "low-poly isometric 3D-flat render, clean facets and long shadows",
    "silhouette shadow-theater, black cutouts against glowing backdrops",
    "mid-century atomic-age illustration, textured shapes and off-register print",
    "illuminated-manuscript margins, gold leaf and flat medieval figures",
    "risograph two-ink print, grainy overlap of fluorescent and navy",
    "noir ink-wash editorial cartoon, dramatic hard shadows",
    # proven-viral reference looks (user-supplied examples, 2026-07-05)
    "ember-glow dark fable art: near-black scene lit by ONE smoldering red glow, "
    "expressive cartoon animals with huge readable emotion, cracked scorched earth "
    "and bare twisted branches",
    "clean stickman comic: simple round-headed white figure with an expressive face "
    "inside a detailed muted real-world scene, one bright accent light source",
    "chibi mascot documentary: big-headed blank-faced white figure in crisp corporate "
    "and industrial environments, soft warm render, tiny identical clones in the "
    "background",
    "parchment history comic: warm candlelit palette, expressive doodle people in "
    "period dress, aged-paper texture and engraved-frame borders",
]
_TONES = [
    "deadpan and dry", "quietly ominous", "awestruck and curious",
    "clinical and forensic", "wry and conspiratorial-but-factual",
    "elegiac and haunting", "calm and reassuring like late-night radio",
]


def _dice(rng: random.Random) -> Dict:
    return {"subject": rng.choice(_SUBJECTS),
            "subject_b": rng.choice(_SUBJECTS),
            "aesthetic": rng.choice(_AESTHETICS),
            "tone": rng.choice(_TONES)}


# --- concept generation ---------------------------------------------------------
_CONCEPT_KEYS = ("name", "id", "niche", "tagline", "audience", "video_types",
                 "brief", "style_suffix", "negative_style", "music_vibe", "voice",
                 "voice_instruct", "accent", "thumb_template", "topic_bank",
                 "example_titles", "seo_keywords")


def _prompt(dice: Dict, hint: Optional[str]) -> str:
    existing = [f"- {c.get('name')}: {c.get('niche', '')[:90]}"
                for c in channels.load()]
    return f"""Invent ONE new faceless YouTube channel concept for a fully automated
documentary/explainer pipeline (one narrator voice over illustrated 2D stills with
subtle animation — no live action, no on-screen text, no real faces).

INSPIRATION DICE (combine, twist, or replace — but be specific and distinct):
- subject area: {dice['subject']} (or: {dice['subject_b']})
- visual style seed: {dice['aesthetic']}
- narrator tone: {dice['tone']}
{f'- USER HINT (must honor): {hint}' if hint else ''}

MUST be clearly different from the existing channels:
{chr(10).join(existing) if existing else '- (none yet)'}

Return ONLY one JSON object, exactly this shape:
{{"channels": [{{
  "name": "channel name, 2-4 memorable words",
  "id": "kebab-case-slug",
  "niche": "one sentence: what every video is about, specific enough to write 100 videos",
  "tagline": "max 8 words",
  "audience": "who watches and why they binge",
  "video_types": "the repeatable formats, e.g. '9-minute narrated deep-dives, 2/week; 45s vertical shorts cut from each'",
  "brief": "3-4 sentences: how every script opens (cold open on the most gripping moment), escalates, and pays off; the narrator persona",
  "style_suffix": "ONE paragraph of 40-70 words of concrete art direction for every image: medium, line quality, a named 3-4 color palette, lighting, composition, texture. Flat illustrated 2D only, no photorealism.",
  "negative_style": "comma-separated things to avoid in images",
  "music_vibe": "6-12 words describing the instrumental score bed",
  "voice": "Ryan or Aiden",
  "voice_instruct": "1-2 sentences directing the narrator's delivery — calm, natural, human prosody; fit the tone",
  "accent": "#hex brand color that matches the palette",
  "thumb_template": "one of: spotlight, case-file, reveal, split, bar",
  "topic_bank": ["10 concrete first-video topics, each a specific true story or subject"],
  "example_titles": ["5 clickable video titles under 60 chars, no clickbait lies"],
  "seo_keywords": ["10 short search keywords"]
}}]}}"""


_FALLBACKS: List[Dict] = [
    {"name": "Felt Tip Front Lines",
     "niche": "History's strangest battles and military blunders, mapped out in "
              "stick-figure war-room diagrams",
     "tagline": "History, badly drawn. Accurately told.",
     "audience": "18-35 history bingers who want the story, not the lecture",
     "video_types": "8-11 min narrated map-and-diagram deep-dives, 2/week; shorts from each",
     "brief": "Cold-open on the most absurd decision of the battle. Walk the map stake "
              "by stake — every scene one diagram, one idea. Payoff: the one detail "
              "historians still argue about. Narrator is dry, amused, precise.",
     "style_suffix": "minimal stick-figure diagram illustration on warm aged paper, "
                     "confident felt-tip marker linework, flat muted sand and slate "
                     "tones with one signal-red accent per scene, simple map shapes and "
                     "arrows, soft paper grain, clean uncluttered composition, gentle "
                     "top-down lighting",
     "negative_style": "photorealistic, 3d render, readable text, gibberish letters, "
                       "cluttered, neon, watermark",
     "music_vibe": "quiet snare taps, low strings, patient ticking tension, sparse",
     "voice": "Ryan",
     "voice_instruct": "A dry, calm history narrator with a hint of amusement — even "
                       "pace, natural human rises and falls, never theatrical.",
     "accent": "#c0392b", "thumb_template": "split",
     "topic_bank": ["The Battle of Karánsebes — an army that defeated itself",
                    "Operation Mincemeat — the corpse that fooled Hitler",
                    "The Emu War — Australia vs. the birds",
                    "The Maginot Line — the perfect wall in the wrong place",
                    "The Ghost Army — inflatable tanks that saved thousands",
                    "The Charge of the Light Brigade — one mistranslated order",
                    "The Zimmermann Telegram — one telegram, one world war",
                    "The Trojan Horse of Troy VII — what archaeology actually found",
                    "The Winter War — how Finland embarrassed the Red Army",
                    "Napoleon's march on Moscow, told by the thermometer"],
     "example_titles": ["The Army That Attacked Itself (and Lost)",
                        "One Dead Body Fooled the Entire Wehrmacht",
                        "Australia Declared War on Birds. The Birds Won.",
                        "The Perfect Fortress France Built in the Wrong Place",
                        "The Fake Army Made of Balloons That Saved D-Day"],
     "seo_keywords": ["military history", "battle explained", "history documentary",
                      "war mistakes", "map history", "animated history",
                      "strange history", "blunders", "world war", "tactics"]},
    {"name": "Blue Margin",
     "niche": "Engineering disasters and near-misses, reconstructed as calm blueprint "
              "post-mortems — what was drawn, what was built, what gave way",
     "tagline": "Every failure was designed first.",
     "audience": "20-45 engineering-curious viewers who love calm technical stories",
     "video_types": "10-min blueprint post-mortems, weekly; 60s 'one bolt' shorts",
     "brief": "Cold-open at the moment of failure. Rewind to the drawing board and move "
              "forward decision by decision — each scene one drawing, one compromise. "
              "Payoff: the single change that would have saved it. Narrator is calm, "
              "clinical, quietly humane.",
     "style_suffix": "technical blueprint illustration, crisp white and cyan line art on "
                     "deep drafting-blue paper, fine hatching and measured dimension "
                     "arrows, one amber warning accent per scene, subtle grid texture, "
                     "clean geometric composition, soft even lighting",
     "negative_style": "photorealistic, 3d render, readable text, gibberish letters, "
                       "cluttered, warm colors, watermark",
     "music_vibe": "slow airy synth pads, faint metallic pulses, patient and clinical",
     "voice": "Aiden",
     "voice_instruct": "A calm, precise narrator like a safety investigator reading "
                       "findings — measured, low, natural prosody, quietly humane.",
     "accent": "#2e86c1", "thumb_template": "bar",
     "topic_bank": ["The Tacoma Narrows Bridge — the wind nobody calculated",
                    "The Hyatt Regency walkway — one changed drawing, 114 lives",
                    "The Comet — the first jetliner and its square windows",
                    "Chernobyl's RBMK — a reactor designed to lie",
                    "The Vasa — the warship that sank in its own harbor",
                    "Apollo 13's oxygen tank — a spec nobody re-read",
                    "The Citicorp Center secret — a student's phone call",
                    "The Titanic's rivets — metallurgy on a deadline",
                    "The Banqiao Dam cascade — 62 dams in one night",
                    "The Therac-25 — software that overdosed patients"],
     "example_titles": ["One Changed Drawing Killed 114 People",
                        "The Bridge That Danced Itself to Death",
                        "A Student's Phone Call Saved This Skyscraper",
                        "The Warship That Sank 20 Minutes Into Its First Trip",
                        "Why the First Jetliner Kept Falling Out of the Sky"],
     "seo_keywords": ["engineering disaster", "structural failure", "blueprint",
                      "post-mortem", "bridge collapse", "design flaw",
                      "engineering explained", "documentary", "safety", "history"]},
    {"name": "The Paper Abyss",
     "niche": "Deep-sea discoveries, vanished vessels and what the ocean gave back — "
              "told in layered paper-cutout dioramas",
     "tagline": "The sea keeps excellent records.",
     "audience": "16-40 mystery and ocean-documentary bingers",
     "video_types": "9-min narrated dives, 2/week; discovery-moment shorts",
     "brief": "Cold-open on the object found. Sink through the story in layers — the "
              "voyage, the loss, the search, the find — one diorama per beat. Payoff: "
              "what the find changed. Narrator is hushed, awestruck, unhurried.",
     "style_suffix": "layered paper-cutout diorama illustration, deep teal to abyssal "
                     "navy card-stock gradients with bone-white and lantern-amber "
                     "accents, soft drop shadows between layers, delicate torn-paper "
                     "texture, single shaft of light from above, spacious composition",
     "negative_style": "photorealistic, 3d render, readable text, gibberish letters, "
                       "cluttered, neon, gore, watermark",
     "music_vibe": "slow deep ambient drones, soft sonar pings, distant whale calls, calm",
     "voice": "Ryan",
     "voice_instruct": "A hushed, awestruck narrator telling sea stories after dark — "
                       "slow, warm, natural breathing pauses, never theatrical.",
     "accent": "#1f7a8c", "thumb_template": "reveal",
     "topic_bank": ["The USS Indianapolis — found five kilometers down",
                    "The Antikythera wreck — a computer from 100 BC",
                    "MH370's debris — what the barnacles knew",
                    "The Endurance — Shackleton's ship, perfectly preserved",
                    "The Mary Rose — a Tudor warship raised whole",
                    "The bloop — the sound that wasn't a monster",
                    "The SS Waratah — 211 people, no wreck, ever",
                    "The Franklin Expedition — two ships under the ice",
                    "The Milwaukee's gold — treasure law in open water",
                    "The Vasa's sister mystery — archives vs. sonar"],
     "example_titles": ["They Found Her Five Kilometers Down",
                        "A 2,000-Year-Old Computer From the Sea Floor",
                        "The Ship That Vanished With 211 People Aboard",
                        "Shackleton's Lost Ship Looked Brand New",
                        "The Sound From the Deep That Fooled Everyone"],
     "seo_keywords": ["shipwreck", "deep sea", "ocean mystery", "discovery",
                      "underwater", "expedition", "maritime history", "vanished",
                      "documentary", "sonar"]},
    {"name": "Gilt & Grift",
     "niche": "History's most audacious cons, forgeries and financial manias, told as "
              "art-deco morality plays about money",
     "tagline": "Every fortune has a magician.",
     "audience": "20-45 finance-true-crime crossover viewers",
     "video_types": "8-10 min narrated cons, 2/week; 'the moment it broke' shorts",
     "brief": "Cold-open at the moment the lie is biggest. Build the con brick by brick "
              "— the mark, the hook, the escalation, the wobble, the collapse. Payoff: "
              "where the money actually went. Narrator is wry, precise, faintly amused.",
     "style_suffix": "art-deco poster illustration, bold geometric shapes and stepped "
                     "sunburst motifs, champagne-gold and jet-black and ivory with one "
                     "emerald accent, strong diagonal composition, subtle foil texture, "
                     "dramatic uplighting, clean uncluttered frames",
     "negative_style": "photorealistic, 3d render, readable text, gibberish letters, "
                       "cluttered, pastel, watermark",
     "music_vibe": "slinky muted brass, brushed swing drums, sly bass, low simmer",
     "voice": "Aiden",
     "voice_instruct": "A wry, unhurried storyteller letting you in on the trick — "
                       "conversational, precise, small human smiles in the voice.",
     "accent": "#c9a227", "thumb_template": "case-file",
     "topic_bank": ["Victor Lustig — the man who sold the Eiffel Tower twice",
                    "The Tulip Mania — the flower that broke Holland",
                    "Charles Ponzi's 45 days of genius",
                    "Han van Meegeren — the forger who fooled the Nazis",
                    "The South Sea Bubble — Newton lost a fortune",
                    "Anna Delvey and the invention of a person",
                    "The Salad Oil Swindle that shook Wall Street",
                    "Gregor MacGregor — the country that didn't exist",
                    "The Great Diamond Hoax of 1872",
                    "Bre-X — the gold mine made of nothing"],
     "example_titles": ["He Sold the Eiffel Tower. Twice.",
                        "The Fake Country That Fooled 250 Investors",
                        "Isaac Newton Lost a Fortune on This Bubble",
                        "The Forger Whose Fakes Fooled the Nazis",
                        "A Gold Mine Made of Absolutely Nothing"],
     "seo_keywords": ["con artist", "scam", "financial history", "fraud", "forgery",
                      "ponzi", "bubble", "true crime", "money", "swindle"]},
]


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48]
    return s or f"channel-{uuid.uuid4().hex[:6]}"


def _clamp(v, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _clamp_list(v, n: int, each: int = 120) -> List[str]:
    if not isinstance(v, list):
        return []
    return [_clamp(x, each) for x in v if _clamp(x, each)][:n]


def _sanitize(c: Dict, dice: Dict) -> Dict:
    """Never trust a small model: clamp, default, and validate every field."""
    fb = _FALLBACKS[0]
    out = {k: c.get(k) for k in _CONCEPT_KEYS}
    out["name"] = _clamp(out["name"], 48) or "Untitled Channel"
    out["id"] = _slug(_clamp(out["id"], 48) or out["name"])
    out["niche"] = _clamp(out["niche"], 300) or f"Narrated stories about {dice['subject']}"
    out["tagline"] = _clamp(out["tagline"], 80)
    out["audience"] = _clamp(out["audience"], 200)
    out["video_types"] = _clamp(out["video_types"], 200) or "narrated deep-dives, 2/week"
    out["brief"] = _clamp(out["brief"], 700) or fb["brief"]
    out["style_suffix"] = _clamp(out["style_suffix"], 700)
    if len(out["style_suffix"]) < 40:      # art direction is load-bearing
        out["style_suffix"] = f"{dice['aesthetic']}, flat illustrated 2D, cohesive " \
                              "3-color palette, clean uncluttered composition, " \
                              "dramatic single-source lighting, subtle print texture"
    neg = _clamp(out["negative_style"], 300)
    for must in ("readable text", "gibberish letters", "photorealistic", "watermark"):
        if must not in neg:
            neg = (neg + ", " if neg else "") + must
    out["negative_style"] = neg
    out["music_vibe"] = _clamp(out["music_vibe"], 160) or fb["music_vibe"]
    out["voice"] = out["voice"] if out["voice"] in _VOICES else "Ryan"
    out["voice_instruct"] = _clamp(out["voice_instruct"], 400) or (
        "A calm, natural documentary narrator — even, unhurried, real human "
        "prosody, never theatrical.")
    accent = _clamp(out["accent"], 9)
    out["accent"] = accent if re.match(r"^#[0-9a-fA-F]{6}$", accent) else "#e6a94b"
    out["thumb_template"] = (out["thumb_template"]
                             if out["thumb_template"] in _THUMB_TEMPLATES else "spotlight")
    out["topic_bank"] = _clamp_list(out["topic_bank"], 12) or list(fb["topic_bank"][:5])
    out["example_titles"] = _clamp_list(out["example_titles"], 6, 80)
    out["seo_keywords"] = [k.lower() for k in _clamp_list(out["seo_keywords"], 12, 40)]
    return out


def _invent(dice: Dict, hint: Optional[str], progress) -> Dict:
    try:
        data = writer.generate_json(_prompt(dice, hint), progress)
        raw = (data.get("channels") or [data])[0]
        if not isinstance(raw, dict):
            raise ValueError("no channel object in output")
        return _sanitize(raw, dice)
    except Exception:  # noqa: BLE001 — no LLM / bad JSON → curated fallback
        rng = random.Random(dice["subject"] + dice["aesthetic"])
        return _sanitize(dict(rng.choice(_FALLBACKS)), dice)


# --- roll storage ----------------------------------------------------------------
def _roll_file(rid: str) -> Path:
    return ROULETTE_DIR / rid / "concept.json"


def _payload(rec: Dict) -> Dict:
    """A roll record decorated with servable asset URLs."""
    rid = rec["rid"]
    rdir = ROULETTE_DIR / rid
    assets = []
    for key in _ROLL_SLOTS:
        f = rdir / f"{key}.png"
        if f.exists():
            assets.append({"key": key,
                           "url": f"/roulette/{rid}/{key}.png?t={int(f.stat().st_mtime)}"})
    return {**rec, "assets": assets}


def list_rolls(limit: int = 24) -> List[Dict]:
    if not ROULETTE_DIR.exists():
        return []
    recs = []
    for d in ROULETTE_DIR.iterdir():
        rec = storage.read_json(d / "concept.json", None) if d.is_dir() else None
        if isinstance(rec, dict) and rec.get("rid"):
            recs.append(_payload(rec))
    recs.sort(key=lambda r: r.get("created") or 0, reverse=True)
    return recs[:limit]


def get_roll(rid: str) -> Optional[Dict]:
    rec = storage.read_json(_roll_file(rid), None)
    return _payload(rec) if isinstance(rec, dict) and rec.get("rid") else None


def discard(rid: str) -> bool:
    d = ROULETTE_DIR / rid
    if not d.is_dir() or not (d / "concept.json").exists():
        return False
    dest = config.TRASH_DIR / "roulette" / f"{rid}-{int(time.time())}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    return True


# --- the roll job ------------------------------------------------------------------
def submit_roll(hint: Optional[str] = None) -> str:
    def task(progress) -> Dict:
        rng = random.Random()
        dice = _dice(rng)
        progress("Rolling the dice + inventing the channel (local LLM)…", 0.05)
        concept = _invent(dice, (hint or "").strip() or None,
                          lambda s, f: progress(s, 0.05 + 0.35 * f))

        rid = uuid.uuid4().hex[:8]
        rdir = ROULETTE_DIR / rid
        rdir.mkdir(parents=True, exist_ok=True)

        # A channel-shaped dict is all the fixed brand graph needs.
        pseudo = {"id": f"roll-{rid}", "niche": concept["niche"],
                  "defaults": {"style_suffix": concept["style_suffix"],
                               "negative_style": concept["negative_style"]}}
        seed_offset = rng.randrange(1_000_000)
        wf, prefix_map = build_graph(pseudo, seed_offset, only=_ROLL_SLOTS)
        (rdir / "graph.json").write_text(json.dumps(wf, indent=2), encoding="utf-8")
        # brainstormer graphs land in ComfyUI's library too — nothing to drag
        publish_graph_to_comfy(f"roulette_{rid}_{concept.get('id') or 'roll'}", wf)

        progress("Starting ComfyUI / krea2…", 0.45)
        comfy_engine.ensure_running(progress=lambda s, f: progress(s, 0.45 + 0.05 * f))
        progress(f"Rendering “{concept['name']}” identity (5 stills ≈ 2-3 min)…", 0.5)
        infos = comfy_engine.run_workflow(
            wf, want=("images",), timeout=900,
            progress=lambda s, f: progress(f"Rendering “{concept['name']}”…",
                                           0.5 + 0.45 * f))
        for info in infos:
            fn = info["filename"]
            key = next((v for p, v in prefix_map.items() if v in fn), None)
            if key:
                (rdir / f"{key}.png").write_bytes(comfy_engine.fetch(info))

        rec = {"rid": rid, "created": time.time(), "dice": dice,
               "seed_offset": seed_offset, "hint": (hint or "").strip() or None,
               "concept": concept, "accepted": None, "graph": "graph.json"}
        storage.write_json(_roll_file(rid), rec)
        return {"roll": _payload(rec)}

    return jobs.submit("channel_roulette", task)


# --- keeping a roll ------------------------------------------------------------------
def accept(rid: str, cid: Optional[str] = None, name: Optional[str] = None) -> Dict:
    """Turn a roll into a real channel folder: record + brand stills + accent."""
    rec = storage.read_json(_roll_file(rid), None)
    if not isinstance(rec, dict) or not rec.get("concept"):
        raise ValueError("roll not found")
    if rec.get("accepted"):
        raise ValueError(f"already accepted as channel '{rec['accepted']}'")
    c = rec["concept"]

    want = _slug(cid or c["id"])
    final = want
    for i in range(2, 10):
        if not channels.get(final):
            break
        final = f"{want}-{i}"

    record = {
        "id": final, "name": _clamp(name, 48) or c["name"], "niche": c["niche"],
        "tagline": c["tagline"], "audience": c["audience"],
        "cadence": c["video_types"], "brief": c["brief"],
        "topic_bank": c["topic_bank"], "seo_keywords": c["seo_keywords"],
        "example_titles": c["example_titles"],
        "defaults": {
            "image_model": "krea2", "animate_engine": "wan", "quality": "balanced",
            "preset": "cinematic", "authoring": "assisted", "coverage": "heroes",
            "voice": c["voice"], "language": "English",
            "voice_instruct": c["voice_instruct"],
            "style_suffix": c["style_suffix"], "negative_style": c["negative_style"],
            "music_vibe": c["music_vibe"],
            # accent only — no pinned template, so every video rotates the
            # thumbnail variance pool (high-variance rule, 2026-07-05)
            "thumb": {"accent": c["accent"]},
            "voice_humanize": "natural",
        },
        "youtube": {},
        "roulette": {"rid": rid, "dice": rec.get("dice"),
                     "seed_offset": rec.get("seed_offset")},
    }
    ch = channels.upsert(record)

    # The roll's stills become the channel's brand kit; the graph rides along so
    # the Brand-preview modal + ComfyUI editing keep working.
    bdir = channels.channel_dir(final) / "brand"
    (bdir / "graphs").mkdir(parents=True, exist_ok=True)
    rdir = ROULETTE_DIR / rid
    for key in _ROLL_SLOTS:
        src = rdir / f"{key}.png"
        if src.exists():
            shutil.copy2(src, bdir / f"{key}.png")
    if (rdir / "graph.json").exists():
        shutil.copy2(rdir / "graph.json", bdir / "graphs" / "channel_preview.json")
        publish_graph_to_comfy(f"{final}_channel_preview", rdir / "graph.json")
    storage.write_json(channels.ui_dir(final) / "ui.json", {"accent": c["accent"]})

    rec["accepted"] = final
    storage.write_json(_roll_file(rid), rec)
    return {"channel": channels.get(final), "roll": _payload(rec)}
