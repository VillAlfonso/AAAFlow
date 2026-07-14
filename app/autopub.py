"""Auto-publish: hands-off per-channel upload scheduling (user, 2026-07-14:
"as they were made they're going to be uploaded... in every channel the
videos are automatically uploaded to youtube").

When a produce finishes and the channel opts in (``channel.auto_upload``),
the finished video is packaged (SEO) if it wasn't yet, then uploaded to the
channel's own YouTube account — always PRIVATE-first, with ``publishAt`` set
to the channel's next free schedule slot. Nothing ever goes public except by
the schedule the user configured on the channel (or a manual flip on
YouTube); an unverified OAuth app may hold scheduled flips until verified,
which is Google's gate, not ours.

channel.auto_upload = {"enabled": true, "hour": 18, "every_days": 1}
  hour        local hour each video goes public at (0-23)
  every_days  minimum days between two publishes on the channel

The next slot = the later of (now, last scheduled slot + every_days), at
``hour``:00 local. The chosen slot persists on the channel record so back-to-
back produces stack onto consecutive slots instead of colliding.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from . import channels, packaging, projects, storage, youtube


def _cfg(ch: Dict) -> Dict:
    c = ch.get("auto_upload")
    return c if isinstance(c, dict) else {}


def _next_slot(ch: Dict) -> str:
    cfg = _cfg(ch)
    hour = max(0, min(23, int(cfg.get("hour", 18))))
    every = max(1, int(cfg.get("every_days", 1)))
    now = datetime.now()
    base = now
    last = cfg.get("last_slot")
    if last:
        try:
            prev = datetime.strptime(last, "%Y-%m-%dT%H:%M")
            base = max(base, prev + timedelta(days=every))
        except ValueError:
            pass
    slot = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot <= max(now, base):
        slot += timedelta(days=1)
    return slot.strftime("%Y-%m-%dT%H:%M")


def maybe_auto_upload(pid: str) -> Optional[str]:
    """Produce-completion hook. Returns the upload job id, or None with the
    reason printed (auto-publish must never fail a produce)."""
    project = projects.get_project(pid)
    if not project:
        return None
    ch = channels.get(project.get("channel")) if project.get("channel") else None
    if not ch or not _cfg(ch).get("enabled"):
        return None
    yt = ch.get("youtube") or {}
    if not (yt.get("client_id") and yt.get("refresh_token")):
        print(f"[autopub] {pid}: channel not connected to YouTube — skipped")
        return None
    if project.get("uploads"):
        print(f"[autopub] {pid}: already uploaded — skipped")
        return None
    pdir = projects.project_dir(pid)
    if not sorted((pdir / "video").glob("final_*.mp4")):
        print(f"[autopub] {pid}: no final render — skipped")
        return None

    if not project.get("seo"):
        try:
            packaging.build(pid)
            project = projects.get_project(pid)
        except Exception as exc:  # noqa: BLE001 — upload with basic metadata
            print(f"[autopub] {pid}: packaging failed ({exc}); uploading with "
                  "project title only")

    slot = _next_slot(ch)
    jid = youtube.submit_upload(pid, {"publish_at": slot, "privacy": "private"})
    cfg = {**_cfg(ch), "last_slot": slot}
    channels.upsert({**ch, "auto_upload": cfg})
    seo = project.get("seo") if isinstance(project.get("seo"), dict) else {}
    seo["publish_at"] = slot
    project["seo"] = seo
    projects.save_project(project)
    storage.add_history({
        "id": storage.new_id(), "created": time.time(), "preview": False,
        "kind": "autopub", "project": pid, "project_name": project.get("name"),
        "text_preview": f"Auto-upload queued (goes public {slot})",
    })
    print(f"[autopub] {pid}: upload queued, goes public {slot}")
    return jid
