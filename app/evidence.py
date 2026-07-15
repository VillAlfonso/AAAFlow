"""EVIDENCE CAPTURE: the documents and screenshots that carry a documentary.

The analyzer's verdict (2026-07-15, 584 fern shots): the reference channel is
an EVIDENCE channel. Screenshots (22%) + documents (18%) are 40% of everything
on screen, and 35% of shots exist to PROVE the narrated claim rather than
illustrate it. Generated pictures cannot do that job — a drawing of a court
filing proves nothing. A screenshot of the actual filing does.

So this is a first-class pipeline capability, not an optional MCP toy: it
screenshots PUBLIC pages (court records, government filings, official
statements, archived posts) into a project's `research/evidence/` folder,
logs the source and license of each, and hands them to `receipts.py`, which
floats them in, eases into the referenced region ON THE SPOKEN WORD and sweeps
a marker highlight across it.

COPYRIGHT (be honest, stay safe):
  * US government works (justice.gov, courts, FBI, congress) are PUBLIC
    DOMAIN. These are the best evidence and carry no risk.
  * Wikimedia PD/CC via `app/archival.py` covers photographs.
  * Screenshots of public web pages for commentary are standard documentary
    practice; the page's content may still be copyrighted, so keep them
    incidental, credited, and never the whole video.
  * We do NOT scrape news photography or broadcast footage, which is what the
    reference channel leans on under fair-use commentary.
Every capture is written to the project's research sources, so the SEO
description credits it automatically.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import projects, storage

# domains we treat as public-domain US government works
GOV = re.compile(r"\.(gov|mil)(/|$)|justice\.gov|uscourts\.gov|fbi\.gov", re.I)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def _license_for(url: str) -> str:
    if GOV.search(url or ""):
        return "public domain (US government work)"
    return "screenshot of a public page, used as documentary evidence"


def capture(url: str, dst: Path, *, selector: Optional[str] = None,
            full_page: bool = False, width: int = 1600, height: int = 1000,
            wait_ms: int = 2500, timeout_ms: int = 45000) -> Optional[Path]:
    """Screenshot one public page (or one element of it). None on failure."""
    from playwright.sync_api import sync_playwright

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height},
                                    user_agent=UA)
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            if selector:
                el = page.query_selector(selector)
                if el:
                    el.screenshot(path=str(dst), timeout=timeout_ms)
                else:
                    page.screenshot(path=str(dst), full_page=full_page,
                                    timeout=timeout_ms)
            else:
                page.screenshot(path=str(dst), full_page=full_page,
                                timeout=timeout_ms)
            browser.close()
        return dst if dst.exists() else None
    except Exception as exc:  # noqa: BLE001 — a failed capture is never fatal
        print(f"[evidence] {url}: {type(exc).__name__}: {exc}")
        return None


def collect(pid: str, items: List[Dict], progress=None) -> Dict:
    """Capture a list of evidence items into a project.

    item: {url, name, selector?, full_page?, label?, why?}
    Writes research/evidence/<name>.png, records each in project["evidence"]
    and appends the source line so the SEO credits it.
    """
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    pdir = projects.project_dir(pid)
    got: List[Dict] = []
    for i, it in enumerate(items):
        url = it.get("url")
        name = it.get("name") or f"evidence_{i:02d}"
        if progress:
            progress(f"capturing {name} ({i + 1}/{len(items)})",
                     i / max(1, len(items)))
        rel = f"research/evidence/{name}.png"
        out = capture(url, pdir / rel, selector=it.get("selector"),
                      full_page=bool(it.get("full_page")))
        if not out:
            continue
        lic = _license_for(url)
        got.append({"name": name, "file": rel, "url": url,
                    "label": it.get("label") or name.replace("_", " ").title(),
                    "why": it.get("why") or "", "license": lic,
                    "captured": time.strftime("%Y-%m-%d")})

    project["evidence"] = (project.get("evidence") or []) + got
    research = project.setdefault("research", {})
    srcs = research.setdefault("sources", [])
    for g in got:
        line = f"Evidence: {g['label']} — {g['url']} ({g['license']})"
        if line not in srcs:
            srcs.append(line)
    projects.save_project(project)
    storage.add_history({
        "id": storage.new_id(), "created": time.time(), "preview": False,
        "kind": "evidence", "project": pid, "project_name": project.get("name"),
        "text_preview": f"Captured {len(got)} evidence document(s)",
    })
    if progress:
        progress("evidence captured", 1.0)
    return {"captured": len(got), "items": got}


def attach_to_scene(pid: str, sid, name: str, *, focus: Optional[Dict] = None,
                    sync: Optional[str] = None) -> Dict:
    """LOCK a captured document in as a scene's picture (the receipts move).

    The scene is skipped by generation (`image_locked`), so it is never
    replaced by a drawing, and `receipts.py` floats it in, zooms to the focus
    region on the spoken word and sweeps a highlight across it.
    """
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    ev = next((e for e in (project.get("evidence") or [])
               if e.get("name") == name), None)
    if not ev:
        raise ValueError(f"no captured evidence named {name}")
    sc = projects.get_scene(project, sid)
    if not sc:
        raise ValueError(f"scene {sid} not found")
    sc["image_file"] = ev["file"]
    sc["image_locked"] = True
    sc["no_video"] = True                    # a document is a still, not a clip
    sc.setdefault("status", {})["images"] = "ready"
    sc["receipt"] = {"focus": focus or {"x": 0.5, "y": 0.42, "w": 0.5, "h": 0.3},
                     "highlight": True, "sync": sync}
    sc["ref"] = {"label": ev.get("label"), "file": ev["file"]} if False else sc.get("ref")
    projects.save_project(project)
    return {"scene": sid, "evidence": name, "file": ev["file"]}
