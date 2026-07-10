"""Local web research: facts, dates and REFERENCE IMAGES for a story.

User rule (2026-07-10): given a topic, the system should find the dates and
the people involved, and most importantly download pictures of the integral
references (a person mentioned by name, a key item, a key place). Those
pictures are later edited into the video at the first spoken mention
(``app/refcards.py``).

Wikipedia/Wikimedia is the source of choice: it covers the true-story niches,
it is machine-friendly (no scraping), and every image carries license
metadata. Each downloaded ref lands in ``<project>/research/refs/`` and is
recorded in ``research/refs.json``:

    [{"file": "research/refs/victor-lustig.jpg", "label": "Victor Lustig",
      "kind": "person", "match": ["victor lustig", "lustig"],
      "source": "https://en.wikipedia.org/wiki/Victor_Lustig",
      "license": "Public domain", "credit": "..."}]

Everything degrades gracefully offline: failures return empty results, never
raise into the pipeline.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from . import jobs, projects, storage

_UA = {"User-Agent": "AAAFlowStudio/1.0 (local desktop video studio)"}
_API = "https://en.wikipedia.org/w/api.php"
_REST = "https://en.wikipedia.org/api/rest_v1"


def _get_json(url: str, timeout: float = 20) -> Optional[Dict]:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception:  # noqa: BLE001
        return None


def _get_bytes(url: str, timeout: float = 60) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        return None


def search_title(query: str) -> Optional[str]:
    """Best-matching Wikipedia article title for a query."""
    q = urllib.parse.urlencode({"action": "opensearch", "search": query,
                                "limit": 1, "namespace": 0, "format": "json"})
    data = _get_json(f"{_API}?{q}")
    try:
        return data[1][0] if data and data[1] else None
    except Exception:  # noqa: BLE001
        return None


def summary(title: str) -> Optional[Dict]:
    """REST summary: extract, canonical url, thumbnail/original image url."""
    t = urllib.parse.quote(title.replace(" ", "_"), safe="")
    return _get_json(f"{_REST}/page/summary/{t}")


def extract(title: str, chars: int = 6000) -> str:
    """Plain-text article extract (the fact source for the writer)."""
    q = urllib.parse.urlencode({
        "action": "query", "prop": "extracts", "explaintext": 1,
        "exchars": int(chars), "redirects": 1, "format": "json",
        "titles": title})
    data = _get_json(f"{_API}?{q}")
    try:
        pages = data["query"]["pages"]
        return next(iter(pages.values())).get("extract") or ""
    except Exception:  # noqa: BLE001
        return ""


def _lead_image(title: str) -> Optional[Dict]:
    """Lead image of an article: {url, file_title} (None when there is none)."""
    q = urllib.parse.urlencode({
        "action": "query", "prop": "pageimages", "piprop": "original|name",
        "redirects": 1, "format": "json", "titles": title})
    data = _get_json(f"{_API}?{q}")
    try:
        page = next(iter(data["query"]["pages"].values()))
        orig = page.get("original") or {}
        if not orig.get("source"):
            return None
        return {"url": orig["source"],
                "file_title": "File:" + page.get("pageimage", "")}
    except Exception:  # noqa: BLE001
        return None


def _image_license(file_title: str) -> Dict:
    """License short-name + artist for a Commons/Wikipedia file page."""
    q = urllib.parse.urlencode({
        "action": "query", "prop": "imageinfo", "iiprop": "extmetadata",
        "format": "json", "titles": file_title})
    data = _get_json(f"{_API}?{q}")
    try:
        page = next(iter(data["query"]["pages"].values()))
        meta = page["imageinfo"][0]["extmetadata"]
        lic = (meta.get("LicenseShortName") or {}).get("value") or ""
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value") or "")
        return {"license": lic.strip(), "credit": artist.strip()[:120]}
    except Exception:  # noqa: BLE001
        return {"license": "", "credit": ""}


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:60] or "ref"


def _aliases(label: str, kind: str, extra: Optional[List[str]] = None) -> List[str]:
    """Phrases whose first spoken mention triggers the on-screen ref card."""
    out = [label.lower()]
    parts = label.split()
    if kind == "person" and len(parts) >= 2 and len(parts[-1]) > 3:
        out.append(parts[-1].lower())          # surname alone counts
    for a in (extra or []):
        a = (a or "").strip().lower()
        if a and a not in out:
            out.append(a)
    return out


def fetch_refs(pid: str, entities: List[Dict], progress=None) -> Dict:
    """Download reference images for entities into <project>/research/refs/.

    entities: [{label, kind: person|place|item, query?, aliases?[]}]
    Returns {found: [...], missed: [...]} and merges research/refs.json.
    Wikipedia lead images only, license recorded; a miss is fine, the video
    simply has no card for that entity.
    """
    pdir = projects.project_dir(pid)
    refs_dir = pdir / "research" / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = pdir / "research" / "refs.json"
    manifest: List[Dict] = storage.read_json(manifest_path, None) or []
    have = {r.get("label", "").lower() for r in manifest}

    found, missed = [], []
    for i, ent in enumerate(entities or []):
        label = (ent.get("label") or "").strip()
        if not label or label.lower() in have:
            continue
        kind = (ent.get("kind") or "person").strip().lower()
        if progress:
            progress(f"Reference image: {label}", 0.1 + 0.8 * i / max(len(entities), 1))
        title = search_title(ent.get("query") or label)
        img = _lead_image(title) if title else None
        if not img:
            missed.append(label)
            continue
        data = _get_bytes(img["url"])
        if not data or len(data) < 2048:
            missed.append(label)
            continue
        ext = Path(urllib.parse.urlparse(img["url"]).path).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        rel = f"research/refs/{_slug(label)}{ext}"
        (pdir / rel).write_bytes(data)
        lic = _image_license(img["file_title"]) if img.get("file_title") else {}
        entry = {
            "file": rel, "label": label, "kind": kind,
            "match": _aliases(label, kind, ent.get("aliases")),
            "source": f"https://en.wikipedia.org/wiki/{urllib.parse.quote((title or label).replace(' ', '_'))}",
            "image_url": img["url"],
            "license": lic.get("license", ""), "credit": lic.get("credit", ""),
            "fetched": time.time(),
        }
        manifest.append(entry)
        have.add(label.lower())
        found.append(entry)

    storage.write_json(manifest_path, manifest)
    # image credits ride into the SEO Sources block (auto-attribution rule)
    if found:
        p = projects.get_project(pid)
        if p is not None:
            r = p.setdefault("research", {})
            srcs = r.setdefault("sources", [])
            for e in found:
                lic = f" ({e['license']})" if e.get("license") else ""
                item = {"title": f"Image: {e['label']}{lic}", "url": e["source"]}
                if not any(s.get("url") == item["url"] and
                           str(s.get("title", "")).startswith("Image:")
                           for s in srcs if isinstance(s, dict)):
                    srcs.append(item)
            projects.save_project(p)
    return {"found": found, "missed": missed, "total": len(manifest)}


def submit_fetch_refs(pid: str, entities: List[Dict]) -> str:
    if not projects.get_project(pid):
        raise ValueError("Project not found.")
    if not entities:
        raise ValueError("No entities given.")

    def task(progress):
        return fetch_refs(pid, entities, progress=progress)

    return jobs.submit("fetch_refs", task, pid=pid)


def research_topic(queries: List[str], max_pages: int = 3) -> Dict:
    """Facts digest for the writer: per-page extracts + sources + keywords."""
    facts: List[str] = []
    sources: List[Dict] = []
    keywords: List[str] = []
    seen = set()
    for q in (queries or [])[:max_pages]:
        title = search_title(q)
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        text = extract(title, chars=5000)
        if not text:
            continue
        facts.append(f"### {title}\n{text.strip()}")
        sources.append({
            "title": f"Wikipedia: {title}",
            "url": "https://en.wikipedia.org/wiki/"
                   + urllib.parse.quote(title.replace(" ", "_"))})
        keywords.append(title)
        for y in re.findall(r"\b(1[6-9]\d\d|20[0-2]\d)\b", text)[:4]:
            if y not in keywords:
                keywords.append(y)
    return {"facts": facts, "sources": sources, "keywords": keywords[:14]}
