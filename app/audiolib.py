"""Royalty-free audio libraries — real music beds + SFX for every video.

Two free-tier providers, each behind a small stdlib-urllib client (no new deps):

* **Jamendo** (music beds) — ``api.jamendo.com/v3.0/tracks``. 500k+ CC-licensed
  instrumentals, searchable by mood/genre tags, duration and popularity. We keep
  only tracks whose license permits **commercial** use (exclude Non-Commercial).
* **Freesound** (SFX / ambience) — ``freesound.org/apiv2/search/text``. Huge
  Creative-Commons catalogue; we prefer **CC0** (no attribution). The freely
  accessible HQ-preview mp3 is what we download (original-file download needs
  OAuth2; the preview is plenty for a background stinger).

Keys are pasted by the user in Settings · Audio (``settings.audio``) — each has
a free tier. **No key ⇒ the provider reports unavailable** and the scorer falls
back to local ACE-Step generation + procedural stingers, so a build never
depends on the network.

Everything downloaded is logged to ``data/audio_library/ledger.json`` with its
license + source URL (the "keep the download record" rule), and
``attribution_line`` turns a ledger entry into a credit the packager appends to
the video description automatically.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from . import config, storage

_UA = "AAAFlowStudio/1.0 (+local)"
_LEDGER = config.AUDIO_LIB_DIR / "ledger.json"
_TIMEOUT = 20


# --- settings / status -------------------------------------------------------
def _cfg() -> Dict:
    return (storage.get_settings().get("audio") or {})


def jamendo_id() -> str:
    return (_cfg().get("jamendo_client_id") or "").strip()


def freesound_token() -> str:
    return (_cfg().get("freesound_token") or "").strip()


def status() -> Dict:
    led = ledger()
    return {
        "jamendo": bool(jamendo_id()),
        "freesound": bool(freesound_token()),
        "prefer": _cfg().get("prefer", "library"),
        "attribution": bool(_cfg().get("attribution", True)),
        "cache": {
            "music": sum(1 for e in led if e.get("kind") == "music"),
            "sfx": sum(1 for e in led if e.get("kind") == "sfx"),
        },
    }


# --- ledger ------------------------------------------------------------------
def ledger() -> List[Dict]:
    return storage.read_json(_LEDGER, []) or []


def _ledger_add(entry: Dict) -> None:
    led = ledger()
    if not any(e.get("cache_id") == entry.get("cache_id") for e in led):
        led.append(entry)
        storage.write_json(_LEDGER, led)


def get_ledger_entry(cache_id: str) -> Optional[Dict]:
    return next((e for e in ledger() if e.get("cache_id") == cache_id), None)


def attribution_line(entry: Dict) -> str:
    """A ready-to-paste credit. CC0 needs none, but we still name the source."""
    lic = (entry.get("license") or "").strip()
    who = entry.get("artist") or entry.get("username") or "Unknown"
    title = entry.get("title") or "Untitled"
    src = entry.get("provider", "").title()
    if "0" in lic and "creative commons 0" in lic.lower():
        return f"“{title}” by {who} (CC0) via {src}"
    lic_part = f" ({lic})" if lic else ""
    return f"“{title}” by {who}{lic_part} via {src}"


# --- HTTP helpers ------------------------------------------------------------
def _get_json(url: str, headers: Optional[Dict] = None) -> Optional[Dict]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — network is best-effort; caller falls back
        return None


def _download(url: str, dest_raw: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r, open(dest_raw, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        return dest_raw.stat().st_size > 1024
    except Exception:  # noqa: BLE001
        try:
            dest_raw.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _to_wav(src: Path, dest_wav: Path, *, seconds: Optional[float] = None) -> bool:
    """Transcode a downloaded mp3/ogg to wav (what the assembler/SFX loader read),
    optionally trimming to `seconds`."""
    cmd = [config.FFMPEG, "-y", "-i", str(src)]
    if seconds:
        cmd += ["-t", f"{float(seconds):.2f}"]
    cmd += ["-ac", "2", "-ar", "44100", str(dest_wav)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        return dest_wav.exists() and dest_wav.stat().st_size > 1024
    except Exception:  # noqa: BLE001
        return False


# --- Jamendo (music beds) ----------------------------------------------------
def search_music(query: str, *, seconds: float = 60.0, instrumental: bool = True,
                 limit: int = 12) -> List[Dict]:
    """Candidate instrumental beds for a mood query (metadata only, no download)."""
    cid = jamendo_id()
    if not cid:
        return []
    tags = "+".join(w for w in urllib.parse.quote(query).split("%20") if w)[:120] or "cinematic"
    lo = max(20, int(seconds))
    params = {
        "client_id": cid, "format": "json", "limit": str(max(1, min(limit, 40))),
        "fuzzytags": tags, "order": "popularity_total_desc",
        "durationbetween": f"{lo}_600", "include": "musicinfo+licenses",
        "audioformat": "mp32", "boost": "popularity_month",
    }
    if instrumental:
        params["vocalinstrumental"] = "instrumental"
    url = "https://api.jamendo.com/v3.0/tracks/?" + urllib.parse.urlencode(params)
    data = _get_json(url)
    if not data or data.get("headers", {}).get("status") != "success":
        return []
    want_commercial = _cfg().get("music_license", "commercial") == "commercial"
    out: List[Dict] = []
    for t in data.get("results", []):
        ccurl = (t.get("license_ccurl") or "").lower()
        # Commercial safety: drop Non-Commercial (NC) licences outright.
        if want_commercial and ("/nc" in ccurl or "nc-" in ccurl or "-nc" in ccurl):
            continue
        dl = t.get("audiodownload") if t.get("audiodownload_allowed") else ""
        stream = dl or t.get("audio") or ""
        if not stream:
            continue
        out.append({
            "provider": "jamendo", "ext_id": str(t.get("id")),
            "title": t.get("name"), "artist": t.get("artist_name"),
            "license": _cc_name(ccurl), "license_url": t.get("license_ccurl"),
            "source_url": t.get("shareurl"), "url": stream,
            "duration": float(t.get("duration") or 0),
            "tags": (t.get("musicinfo", {}).get("tags", {}) or {}).get("genres", []),
        })
    return out


def _cc_name(ccurl: str) -> str:
    u = (ccurl or "").lower()
    if "publicdomain" in u or "/zero" in u:
        return "CC0"
    for code, name in (("by-nc-sa", "CC BY-NC-SA"), ("by-nc-nd", "CC BY-NC-ND"),
                       ("by-nc", "CC BY-NC"), ("by-sa", "CC BY-SA"),
                       ("by-nd", "CC BY-ND"), ("by", "CC BY")):
        if code in u:
            return name
    return "Creative Commons"


# --- Freesound (SFX / ambience) ----------------------------------------------
def search_sfx(query: str, *, max_dur: float = 6.0, limit: int = 10,
               cc0_only: bool = True) -> List[Dict]:
    """Candidate stingers for a cue (metadata + freely-downloadable HQ preview)."""
    tok = freesound_token()
    if not tok:
        return []
    filt = f"duration:[0 TO {max(1.0, float(max_dur)):.1f}]"
    if cc0_only:
        filt += ' license:"Creative Commons 0"'
    params = {
        "query": query, "filter": filt, "sort": "score",
        "page_size": str(max(1, min(limit, 30))),
        "fields": "id,name,duration,license,previews,username,url,tags",
    }
    url = "https://freesound.org/apiv2/search/text/?" + urllib.parse.urlencode(params)
    data = _get_json(url, headers={"Authorization": f"Token {tok}"})
    if not data:
        # CC0 can be sparse for niche cues — retry without the licence filter.
        if cc0_only:
            return search_sfx(query, max_dur=max_dur, limit=limit, cc0_only=False)
        return []
    out: List[Dict] = []
    for s in data.get("results", []):
        prev = (s.get("previews") or {})
        purl = prev.get("preview-hq-mp3") or prev.get("preview-lq-mp3")
        if not purl:
            continue
        out.append({
            "provider": "freesound", "ext_id": str(s.get("id")),
            "title": s.get("name"), "artist": s.get("username"),
            "username": s.get("username"),
            "license": _freesound_license(s.get("license")),
            "license_url": s.get("license"), "source_url": s.get("url"),
            "url": purl, "duration": float(s.get("duration") or 0),
            "tags": s.get("tags", []),
        })
    return out


def _freesound_license(url: Optional[str]) -> str:
    u = (url or "").lower()
    if "publicdomain" in u or "/zero" in u:
        return "Creative Commons 0"
    if "by-nc" in u:
        return "CC BY-NC"
    if "/by/" in u or u.endswith("/by"):
        return "CC BY"
    return "Creative Commons"


# --- fetch (download + transcode + ledger) -----------------------------------
def fetch(cand: Dict, dest_wav: Path, *, kind: str, seconds: Optional[float] = None
          ) -> Optional[Dict]:
    """Download a candidate to `dest_wav` (transcoded), record it in the ledger.
    Returns the ledger entry (with 'path') or None if the network/transcode fails.
    Already-cached files short-circuit."""
    cache_id = f"{cand['provider']}_{cand['ext_id']}"
    entry = get_ledger_entry(cache_id)
    if entry and Path(entry.get("path", "")).exists():
        return entry
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    raw = dest_wav.with_suffix(".dl")
    if not _download(cand["url"], raw):
        return None
    ok = _to_wav(raw, dest_wav, seconds=seconds)
    try:
        raw.unlink(missing_ok=True)
    except OSError:
        pass
    if not ok:
        return None
    entry = {
        "cache_id": cache_id, "kind": kind, "provider": cand["provider"],
        "ext_id": cand["ext_id"], "title": cand.get("title"),
        "artist": cand.get("artist"), "username": cand.get("username"),
        "license": cand.get("license"), "license_url": cand.get("license_url"),
        "source_url": cand.get("source_url"), "duration": cand.get("duration"),
        "tags": cand.get("tags", []), "path": str(dest_wav),
        "file": dest_wav.name, "downloaded": time.time(),
    }
    entry["attribution"] = attribution_line(entry)
    _ledger_add(entry)
    return entry
