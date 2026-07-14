"""Archival media fetcher: REAL public-domain art for history scenes.

The reference channels' screens are mostly real media (paintings, engravings,
period photos, maps) — the single strongest de-AI lever (user, 2026-07-13:
"formulaic content does not slide"). This module searches Wikimedia Commons
(no key needed), prefers public-domain / CC0 files, downloads them into the
project's ``research/archival/`` folder, logs the license, and can lock them
in as full-frame scene art (``image_file`` + ``image_locked`` — the same
sanctioned-evidence mechanism as receipts).

Attribution-required files (CC BY / CC BY-SA) are accepted but flagged, and
belong in the SEO credits like any other licensed asset. Non-commercial or
unclear licenses are skipped outright.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from . import projects, storage

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "AAAFlowStudio/1.0 (local video studio; archival fetch)"}

_OK_LICENSE = re.compile(r"public domain|cc0|pd-|no restrictions", re.I)
_ATTR_LICENSE = re.compile(r"cc[ -]by(?![ -]nc)", re.I)


def _get(params: Dict) -> Dict:
    qs = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(f"{API}?{qs}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def search(query: str, limit: int = 12, min_width: int = 800) -> List[Dict]:
    """Commons files for a query, best-first: PD/CC0 before CC BY, big before
    small. Each row: {title, url, thumb, width, height, license, attribution,
    needs_credit}."""
    data = _get({
        "action": "query", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6,
        "gsrlimit": limit * 2, "prop": "imageinfo",
        "iiprop": "url|size|extmetadata", "iiurlwidth": 1600,
    })
    rows: List[Dict] = []
    for page in (data.get("query", {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "") or ""
        usage = (meta.get("UsageTerms") or {}).get("value", "") or ""
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "") or "").strip()
        blob = f"{lic} {usage}"
        if _OK_LICENSE.search(blob):
            needs_credit = False
        elif _ATTR_LICENSE.search(blob):
            needs_credit = True
        else:
            continue                      # NC / unclear: never ship it
        w = int(info.get("width") or 0)
        if w < min_width:
            continue
        rows.append({
            "title": page.get("title", ""), "url": info.get("url"),
            "thumb": info.get("thumburl") or info.get("url"),
            "width": w, "height": int(info.get("height") or 0),
            "license": lic or "public domain", "attribution": artist,
            "needs_credit": needs_credit,
        })
    rows.sort(key=lambda r: (r["needs_credit"], -r["width"]))
    return rows[:limit]


def fetch(row: Dict, dest: Path) -> Optional[Path]:
    """Download one search row (the 1600px render, plenty for 1080p)."""
    url = row.get("thumb") or row.get("url")
    if not url:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())
    return dest if dest.exists() else None


def apply_to_scene(pid: str, sid, query: str, pick: int = 0) -> Dict:
    """Search, download and LOCK an archival image as scene art.

    Locked scenes are skipped by batch image regeneration (the receipts
    precedent), so the real art survives produce reruns. Returns the chosen
    row (with the saved path) or raises with the reason."""
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    sc = projects.get_scene(project, sid)
    if not sc:
        raise ValueError(f"Scene {sid} not found.")
    rows = search(query)
    if not rows:
        raise ValueError(f"No usable public-domain result for: {query}")
    row = rows[min(pick, len(rows) - 1)]
    pdir = projects.project_dir(pid)
    ext = Path(urllib.parse.urlparse(row["url"]).path).suffix or ".jpg"
    rel = f"research/archival/scene_{projects.scene_key(sid)}{ext}"
    if not fetch(row, pdir / rel):
        raise RuntimeError("Download failed.")
    sc["image_file"] = rel
    sc["image_locked"] = True
    sc.setdefault("status", {})["images"] = "ready"
    sc["archival"] = {"query": query, "title": row["title"],
                      "license": row["license"],
                      "attribution": row["attribution"],
                      "needs_credit": row["needs_credit"]}
    # licensing trail: research sources feed the SEO Sources/Credits block
    research = project.setdefault("research", {})
    srcs = research.setdefault("sources", [])
    line = (f"Image: {row['title']} — {row['license']}"
            + (f" — {row['attribution']}" if row["attribution"] else "")
            + " (Wikimedia Commons)")
    if line not in srcs:
        srcs.append(line)
    projects.save_project(project)
    storage.add_history({
        "id": storage.new_id(), "created": time.time(), "preview": False,
        "kind": "archival", "project": pid, "project_name": project["name"],
        "text_preview": f"Archival art locked on scene {sid}: {row['title']}",
    })
    return {"scene": sid, **row, "file": rel}
