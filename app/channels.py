"""Channels — persistent identities for running multiple YouTube channels.

A channel owns everything that should stay constant across its videos: the
niche, the art direction, the narrator voice, the editing preset, the engine /
quality choices, the music vibe, and how its scripts get written (pro model vs
assisted small-model mode). Creating a project inside a channel inherits all
of it; the storyboard only has to bring narration + picture subjects.

Stored in ``data/channels.json`` (same JSON-file persistence as every other
library in the app). Seeded once with five ready-to-run sample channels whose
niches are chosen for high CPM / high watch-time; edit or replace them freely.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

from . import config, storage

# ---------------------------------------------------------------------------
# Seed channels. Every default maps to a REAL knob in this system:
#   image_model -> IMAGE_BASES key          preset  -> data/effects_presets.json id
#   animate_engine -> "wan" | "none"        quality -> "max" | "fast"
#   voice -> Qwen3-TTS speaker              authoring -> "pro" | "assisted"
# Styles are deliberately flat/graphic (krea2 at cfg 1.0 holds those best) and
# contain no people-describing clauses, so people-less scenes stay phantom-free.
# ---------------------------------------------------------------------------
SEED_CHANNELS: List[Dict] = [
    {
        "id": "grift",
        "name": "GRIFT",
        "niche": "Con artists, heists & beautiful lies (true-crime storytelling)",
        "tagline": "Every fortune hides a trick.",
        "audience": "18-45, true-crime + finance crossover; binge viewers",
        "why_it_earns": ("True crime is YouTube's most reliable watch-time niche and the "
                         "money angle pulls finance-tier CPMs ($12-25). Endless evergreen "
                         "catalog: every famous con is a ready-made script."),
        "cadence": "2 videos / week",
        "defaults": {
            "image_model": "krea2", "animate_engine": "wan", "quality": "max",
            "preset": "cinematic", "authoring": "pro",
            "voice": "Ryan", "language": "English",
            "voice_instruct": ("Speak like a seasoned documentary narrator telling a "
                               "heist story over a late-night drink - dry, confident, "
                               "a hint of amusement, never rushed."),
            "style_suffix": ("1940s noir editorial-cartoon illustration: confident ink "
                             "linework, flat muted paper tones of charcoal, cream and "
                             "smoke gray with one scarlet accent per scene, dramatic "
                             "hard shadows, subtle paper grain, clean uncluttered "
                             "composition"),
            "negative_style": "photorealistic, 3d render, glossy, neon, cluttered",
            "music_vibe": "smoky noir jazz, upright bass, brushed drums, slow-building tension",
        },
        "brief": ("Open on the con's most outrageous moment, never on biography. "
                  "Escalate stake by stake; the payoff reveals the one detail that "
                  "unravelled it. Tone: admiring of the craft, unsparing about the fall."),
        "topic_bank": [
            "Victor Lustig - the man who sold the Eiffel Tower twice",
            "Anna Delvey - the fake heiress who conned Manhattan",
            "Charles Ponzi - the scheme so big it became a word",
            "George Parker - he sold the Brooklyn Bridge, twice a week",
            "The Bre-X gold hoax - a $6B mine with no gold",
            "Frank Abagnale - the teenage airline pilot who wasn't",
            "The Great Diamond Hoax of 1872",
            "The Hatton Garden heist - pensioners' last job",
            "D.B. Cooper - the only unsolved hijacking in US history",
            "Theranos - one drop of blood, nine billion dollars",
        ],
        "seo_keywords": ["true crime", "con artist", "scam story", "heist",
                         "fraud documentary", "white collar crime", "swindler",
                         "greatest cons", "crime history", "unbelievable true story"],
    },
    {
        "id": "paper-empire",
        "name": "Paper Empire",
        "niche": "How money is made, faked and lost (economics story-explainers)",
        "tagline": "Fortunes on paper. Ruins in practice.",
        "audience": "20-55, personal-finance curious; investor-adjacent",
        "why_it_earns": ("Finance is the highest-CPM category on YouTube ($15-40). "
                         "Collapse stories (hyperinflation, bubbles, frauds) get "
                         "true-crime CTR with finance advertiser rates."),
        "cadence": "1-2 videos / week",
        "defaults": {
            "image_model": "krea2", "animate_engine": "wan", "quality": "max",
            "preset": "parallax-slides", "authoring": "pro",
            "voice": "Aiden", "language": "English",
            "voice_instruct": ("Calm, analytical, slightly ominous - a financial "
                               "insider quietly explaining how the trick works."),
            "style_suffix": ("minimalist low-poly 3D isometric diorama style, matte "
                             "plastic materials, soft studio lighting, muted pastel "
                             "palette with gold accents, generous clean negative "
                             "space, tilt-shift miniature feel"),
            "negative_style": "photorealistic, gritty, cluttered, text, watermark",
            "music_vibe": "minimal tense electronic pulse, ticking percussion, deep sub bass",
        },
        "brief": ("Lead with the absurd number (a trillion-dollar note, a $100M tulip). "
                  "Explain the mechanism in one breath, then ride the collapse. End on "
                  "what it means for the viewer's own money."),
        "topic_bank": [
            "Zimbabwe - the one hundred trillion dollar note",
            "Weimar 1923 - wheelbarrows of cash for bread",
            "Tulip mania - the flower worth more than a house",
            "The Hunt brothers - the men who cornered silver",
            "George Soros - the man who broke the Bank of England",
            "1MDB - the heist of a whole country",
            "Japan's lost decade - when a golf membership cost $3M",
            "How casinos are mathematically unbeatable",
            "The LIBOR scandal - rigging the world's interest rate",
            "Why Concorde lost money at Mach 2",
        ],
        "seo_keywords": ["finance", "economics explained", "money history",
                         "hyperinflation", "market crash", "economic collapse",
                         "investing", "financial crisis", "wealth", "bubble"],
    },
    {
        "id": "borderline",
        "name": "Borderline",
        "niche": "Map oddities & geopolitical absurdities",
        "tagline": "Every border tells a lie.",
        "audience": "16-40, geography/trivia bingers; hugely shareable",
        "why_it_earns": ("Geography-oddity videos are discovery-machine content - "
                         "high CTR thumbnails (a weird map sells itself), evergreen, "
                         "advertiser-safe, and cheap to produce in volume."),
        "cadence": "3 videos / week (volume channel)",
        "defaults": {
            "image_model": "krea2", "animate_engine": "none", "quality": "max",
            "preset": "parallax-slides", "authoring": "assisted",
            "voice": "Serena", "language": "English",
            "voice_instruct": ("Curious, wry, well-traveled tour-guide energy; "
                               "delighted by the absurdity."),
            "style_suffix": ("layered paper-cutout collage style with cartographic "
                             "texture, torn-edge card stock in muted atlas colors of "
                             "sage, sand, slate blue and brick red, subtle drop "
                             "shadows between paper layers, vintage map linework"),
            "negative_style": "photorealistic, satellite photo, text labels, watermark",
            "music_vibe": "warm worldbeat, plucked strings, hand percussion, wanderlust",
        },
        "brief": ("One absurdity per video. Open with the impossible fact stated "
                  "plainly. The paper-cutout style loves aerial/diagram compositions - "
                  "write picture subjects as layered landscapes, not portraits."),
        "topic_bank": [
            "Baarle - the town where the border runs through living rooms",
            "Bir Tawil - the land no country wants",
            "The whisky war - Canada and Denmark's politest conflict",
            "Point Roberts - the American town you need Canada to reach",
            "Why Kaliningrad is Russia, 300 miles from Russia",
            "The India-Bangladesh enclave inside an enclave inside an enclave",
            "The village split in half by the Korean DMZ",
            "Why Alaska isn't Canadian",
            "The Darien Gap - the missing 66 miles of the Pan-American Highway",
            "Istanbul - one city, two continents",
        ],
        "seo_keywords": ["geography", "map facts", "strange borders",
                         "geopolitics", "borders explained", "world map",
                         "countries", "enclave", "territory", "travel facts"],
    },
    {
        "id": "autopsy",
        "name": "Autopsy of a Giant",
        "niche": "Business post-mortems - how famous companies died",
        "tagline": "How giants die.",
        "audience": "20-50, business/tech; LinkedIn-sharer demographic",
        "why_it_earns": ("Business post-mortems combine brand-name search traffic "
                         "(Blockbuster, Nokia, Kodak) with business-tier CPMs "
                         "($10-20) and an inexhaustible topic list."),
        "cadence": "1 video / week",
        "defaults": {
            "image_model": "krea2", "animate_engine": "wan", "quality": "max",
            "preset": "cinematic", "authoring": "pro",
            "voice": "Ryan", "language": "English",
            "voice_instruct": ("A sharp, witty eulogy - respectful of the empire, "
                               "honest about the fatal mistake."),
            "style_suffix": ("1960s screen-print advertising illustration style, bold "
                             "flat two-tone spot colors on off-white with ink navy and "
                             "a single brand accent color, halftone dot shading, "
                             "confident thick outlines, retro commercial-art composition"),
            "negative_style": "photorealistic, 3d render, gradient, text, watermark",
            "music_vibe": "retro lounge groove that slowly sours into minor-key tension",
        },
        "brief": ("Structure every video as a eulogy: the empire at its peak, the "
                  "moment the fatal decision was made (name the meeting, the year, "
                  "the person), the slow bleed, the lesson. One fatal mistake per "
                  "video - not a list."),
        "topic_bank": [
            "Blockbuster - the $50 late fee that built Netflix",
            "Kodak - they invented the digital camera, then buried it",
            "Nokia - from world domination to sold in a decade",
            "BlackBerry - the phone that laughed at the iPhone",
            "Toys R Us - killed by a spreadsheet, not by kids",
            "Pan Am - the airline that sold tickets to the Moon",
            "Quibi - $1.75 billion for six months",
            "Sears - the Amazon of 1900 that forgot what it was",
            "WeWork - the $47B company that owned nothing",
            "Segway - the future that arrived and nobody came",
        ],
        "seo_keywords": ["business case study", "why they failed", "bankruptcy",
                         "rise and fall", "corporate history",
                         "business documentary", "company collapse",
                         "brand history", "startup failure"],
    },
    {
        "id": "night-shift",
        "name": "Night Shift",
        "niche": "Calm dark-science & deep-time mysteries for late-night viewers",
        "tagline": "Strange questions for quiet hours.",
        "audience": "18-40 night owls; falls-asleep-to-videos crowd = massive watch time",
        "why_it_earns": ("Sleepy-curious content earns through session length: viewers "
                         "watch to the end (or past it), which trains the algorithm to "
                         "push the whole catalog. Low edit density = cheapest to make."),
        "cadence": "3 videos / week (volume channel)",
        "defaults": {
            "image_model": "krea2", "animate_engine": "none", "quality": "max",
            "preset": "parallax-slides", "authoring": "assisted",
            "voice": "Vivian", "language": "English",
            "voice_instruct": ("Hushed, soothing, midnight-radio storyteller; "
                               "unhurried, warm, a little awestruck."),
            "style_suffix": ("soft gouache night-scene illustration, deep indigo and "
                             "violet palette with warm amber highlights, gentle paint "
                             "grain, dreamy atmospheric depth, quiet minimal "
                             "composition"),
            "negative_style": "harsh light, saturated, photorealistic, busy, text",
            "music_vibe": "slow ambient drones, warm pads, distant piano, deep calm",
        },
        "brief": ("Pace slower than the other channels: hook is still short, but body "
                  "scenes can breathe at 12-16 words. No jump scares, no alarm - awe "
                  "and calm. End on a gentle unresolved question."),
        "topic_bank": [
            "What is actually at the bottom of the Mariana Trench",
            "Krakatoa - the loudest sound ever recorded on Earth",
            "The day the dinosaurs died, hour by hour",
            "Voyager's golden record - a mixtape for aliens",
            "The Wow! signal - 72 seconds we can't explain",
            "The oldest living thing on Earth",
            "Point Nemo - the loneliest place in the ocean",
            "Why whales sing in a key we changed",
            "The deep-sea gigantism mystery",
            "What falling into a black hole would feel like",
        ],
        "seo_keywords": ["science mystery", "space documentary", "deep ocean",
                         "calm narration", "sleep video", "deep time",
                         "universe explained", "unsolved science",
                         "relaxing documentary", "night video"],
    },
]

# The engine keys create_project understands (projects._apply_engines).
_ENGINE_KEYS = ("image_model", "animate_engine", "quality", "preset", "authoring")


def _now() -> float:
    return time.time()


def load() -> List[Dict]:
    """All channels; the file is seeded with the samples on first touch.

    Existing files get NEW seed fields backfilled (never overwriting edits) so
    upgrades like seo_keywords/youtube appear on already-seeded channels.
    """
    data = storage.read_json(config.CHANNELS_FILE, None)
    if not isinstance(data, list) or not data:
        data = [dict(c, youtube={}, created=_now(), updated=_now(),
                     stats={"projects": 0, "last_project": None})
                for c in SEED_CHANNELS]
        storage.write_json(config.CHANNELS_FILE, data)
        return data
    seeds = {c["id"]: c for c in SEED_CHANNELS}
    changed = False
    for c in data:
        seed = seeds.get(c.get("id"), {})
        if "seo_keywords" not in c and seed.get("seo_keywords"):
            c["seo_keywords"] = list(seed["seo_keywords"])
            changed = True
        if "youtube" not in c:
            c["youtube"] = {}
            changed = True
    if changed:
        storage.write_json(config.CHANNELS_FILE, data)
    return data


def save(chans: List[Dict]) -> List[Dict]:
    storage.write_json(config.CHANNELS_FILE, chans)
    return chans


def get(cid: Optional[str]) -> Optional[Dict]:
    if not cid:
        return None
    for c in load():
        if c.get("id") == cid:
            return dict(c)
    return None


def upsert(channel: Dict) -> Dict:
    cid = (channel.get("id") or "").strip()
    if not cid:
        cid = re.sub(r"[^a-z0-9]+", "-", (channel.get("name") or "").lower()).strip("-")
        if not cid:
            raise ValueError("Channel needs an id or a name.")
        channel["id"] = cid
    chans = load()
    old = next((c for c in chans if c.get("id") == cid), None)
    if old:
        merged = storage.deep_merge(old, channel)
        merged["updated"] = _now()
        chans = [merged if c.get("id") == cid else c for c in chans]
        save(chans)
        return merged
    channel.setdefault("defaults", {})
    channel.setdefault("stats", {"projects": 0, "last_project": None})
    channel["created"] = channel["updated"] = _now()
    save(chans + [channel])
    return channel


def remove(cid: str) -> bool:
    chans = load()
    kept = [c for c in chans if c.get("id") != cid]
    if len(kept) != len(chans):
        save(kept)
        return True
    return False


def note_project(cid: str, pid: str) -> None:
    """Remember that a project was created in this channel (stats on the card)."""
    chans = load()
    for c in chans:
        if c.get("id") == cid:
            st = c.setdefault("stats", {})
            st["projects"] = int(st.get("projects") or 0) + 1
            st["last_project"] = pid
            c["updated"] = _now()
            save(chans)
            return


def default_engines(channel: Dict) -> Dict:
    """The channel's defaults in the shape projects._apply_engines expects."""
    d = (channel or {}).get("defaults") or {}
    return {k: d[k] for k in _ENGINE_KEYS if d.get(k)}


def authoring_prompt(channel: Dict, topic: Optional[str] = None) -> str:
    """The full copy-paste prompt for writing this channel's next script.

    Bundles the storyboard authoring spec with the channel's brief, tone and
    topic bank, so ANY model (including a small one in assisted mode) receives
    identical instructions. The channel supplies the art direction - the writer
    must leave global_style_suffix empty.
    """
    spec = ""
    tpl = config.BASE_DIR / "storyboard_v3_prompt.md"
    if tpl.exists():
        spec = tpl.read_text(encoding="utf-8")
    d = (channel or {}).get("defaults") or {}
    lines = [
        f"# CHANNEL BRIEF — {channel.get('name')} ({channel.get('niche')})",
        "",
        f"Tagline: {channel.get('tagline', '')}",
        f"Audience: {channel.get('audience', '')}",
        f"Writing brief: {channel.get('brief', '')}",
        "",
        "Rules for THIS channel:",
        "- Leave video.global_style_suffix EMPTY — the channel's art direction "
        "is applied automatically on import.",
        "- Write picture subjects that suit this look: " + (d.get("style_suffix") or "")[:160] + "…",
        f"- Narration will be voiced by one narrator ({d.get('voice', 'Ryan')}); "
        "write for a single continuous read.",
    ]
    if topic:
        lines += ["", f"TODAY'S TOPIC: {topic}"]
    else:
        bank = channel.get("topic_bank") or []
        if bank:
            lines += ["", "Pick ONE topic (or take the first unused):"]
            lines += [f"- {t}" for t in bank]
    return spec + "\n\n---\n\n" + "\n".join(lines) + "\n"
