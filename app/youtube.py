"""YouTube uploads — per-channel OAuth, resumable upload, thumbnail set.

Each channel carries its own Google OAuth Desktop-client credentials in
``channels.json`` (``channel.youtube``): the user pastes client_id +
client_secret once, clicks Connect (loopback OAuth flow through this local
server), and the refresh token is stored on the channel. Uploads then run as
normal background jobs. Everything speaks urllib — no new dependencies.

Uploads default to **private**: review on YouTube, then publish there.
(Google locks uploads from unverified OAuth apps to private anyway.)
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional

from . import channels, config, jobs, projects


def _redirect_uri() -> str:
    return "http://127.0.0.1:8000" + config.YOUTUBE["redirect_path"]


def auth_url(cid: str) -> str:
    ch = channels.get(cid)
    yt = (ch or {}).get("youtube") or {}
    if not yt.get("client_id"):
        raise ValueError("Set youtube.client_id + client_secret on the channel first "
                         "(Google Cloud Console → OAuth client, type 'Desktop app').")
    q = urllib.parse.urlencode({
        "client_id": yt["client_id"],
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": config.YOUTUBE["scope"],
        "access_type": "offline",
        "prompt": "consent",           # force a refresh_token every time
        "state": cid,
    })
    return f"{config.YOUTUBE['auth_url']}?{q}"


def _token_request(data: Dict) -> Dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(config.YOUTUBE["token_url"], data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def finish_oauth(cid: str, code: str) -> Dict:
    """Exchange the callback code and persist the refresh token on the channel."""
    ch = channels.get(cid)
    yt = (ch or {}).get("youtube") or {}
    if not yt.get("client_id"):
        raise ValueError("channel has no youtube.client_id")
    tok = _token_request({
        "client_id": yt["client_id"], "client_secret": yt.get("client_secret", ""),
        "code": code, "grant_type": "authorization_code",
        "redirect_uri": _redirect_uri(),
    })
    if not tok.get("refresh_token"):
        raise ValueError(f"Google returned no refresh_token: {tok}")
    channels.upsert({"id": cid, "youtube": {"refresh_token": tok["refresh_token"],
                                            "connected": time.time()}})
    return {"connected": True}


def _access_token(yt: Dict) -> str:
    tok = _token_request({
        "client_id": yt["client_id"], "client_secret": yt.get("client_secret", ""),
        "refresh_token": yt["refresh_token"], "grant_type": "refresh_token",
    })
    if not tok.get("access_token"):
        raise RuntimeError(f"token refresh failed: {tok}")
    return tok["access_token"]


def _api_error(exc: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(exc.read().decode())
        reason = detail["error"]["errors"][0].get("reason", "")
        msg = detail["error"].get("message", "")
        if reason == "quotaExceeded":
            return "YouTube API daily quota exceeded — try again after midnight PT."
        return f"{exc.code} {reason}: {msg}"
    except Exception:  # noqa: BLE001
        return f"HTTP {exc.code}"


def submit_upload(pid: str, opts: Optional[Dict] = None) -> str:
    """Upload a project render (default: newest final) to its channel's YouTube.

    opts: file (project-relative mp4), title, description, tags, privacy,
    thumbnail (bool, default True).
    """
    opts = opts or {}
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    ch = channels.get(project.get("channel"))
    if not ch:
        raise ValueError("This project has no channel — uploads are per-channel.")
    yt = ch.get("youtube") or {}
    if not (yt.get("client_id") and yt.get("refresh_token")):
        raise ValueError(f"Channel “{ch.get('name')}” isn't connected to YouTube yet "
                         "(Publish page → Connect).")

    pdir = projects.project_dir(pid)
    rel = opts.get("file")
    if not rel:
        finals = sorted((pdir / "video").glob("final_*.mp4"),
                        key=lambda f: f.stat().st_mtime, reverse=True)
        if not finals:
            raise ValueError("No final render to upload — assemble first.")
        rel = f"video/{finals[0].name}"
    src = pdir / rel
    if not src.exists():
        raise ValueError(f"{rel} not found.")

    seo = project.get("seo") or {}
    title = (opts.get("title") or (seo.get("titles") or [None])[0]
             or project.get("video", {}).get("title") or project.get("name"))[:100]
    description = (opts.get("description") or seo.get("description") or "")[:4900]
    tags = opts.get("tags") or seo.get("tags") or []
    privacy = opts.get("privacy") or yt.get("privacy") or "private"
    category = str(yt.get("category_id") or "27")

    def task(progress) -> Dict:
        progress("Refreshing access token", 0.02)
        token = _access_token(yt)
        meta = {
            "snippet": {"title": title, "description": description,
                        "tags": tags[:60], "categoryId": category},
            "status": {"privacyStatus": privacy,
                       "selfDeclaredMadeForKids": False},
        }
        progress("Starting resumable upload", 0.05)
        size = src.stat().st_size
        init = urllib.request.Request(
            f"{config.YOUTUBE['upload_url']}?uploadType=resumable&part=snippet,status",
            data=json.dumps(meta).encode(), method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Type": "video/mp4",
                     "X-Upload-Content-Length": str(size)})
        try:
            with urllib.request.urlopen(init, timeout=60) as r:
                session = r.headers.get("Location")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(_api_error(exc)) from exc
        if not session:
            raise RuntimeError("YouTube did not return an upload session URL.")

        chunk = config.YOUTUBE["chunk_bytes"]
        sent = 0
        video = None
        with open(src, "rb") as f:
            while sent < size:
                blob = f.read(chunk)
                end = sent + len(blob) - 1
                req = urllib.request.Request(
                    session, data=blob, method="PUT",
                    headers={"Content-Length": str(len(blob)),
                             "Content-Range": f"bytes {sent}-{end}/{size}"})
                try:
                    with urllib.request.urlopen(req, timeout=600) as r:
                        video = json.load(r)          # only the final chunk returns a body
                except urllib.error.HTTPError as exc:
                    if exc.code == 308:               # resume-incomplete: keep going
                        pass
                    else:
                        raise RuntimeError(_api_error(exc)) from exc
                sent += len(blob)
                progress(f"Uploading {sent // 1024 // 1024}/{size // 1024 // 1024} MB",
                         0.05 + 0.85 * sent / size)
        if not video or not video.get("id"):
            raise RuntimeError("Upload finished but YouTube returned no video id.")
        vid = video["id"]

        if opts.get("thumbnail", True):
            thumb = pdir / "thumbnail.png"
            if thumb.exists():
                progress("Setting thumbnail", 0.93)
                treq = urllib.request.Request(
                    f"{config.YOUTUBE['thumb_url']}?videoId={vid}",
                    data=thumb.read_bytes(), method="POST",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "image/png"})
                try:
                    urllib.request.urlopen(treq, timeout=120).read()
                except urllib.error.HTTPError as exc:
                    print(f"[youtube] thumbnail set failed: {_api_error(exc)}")

        url = f"https://youtu.be/{vid}"
        proj = projects.get_project(pid)
        proj.setdefault("uploads", []).insert(0, {
            "video_id": vid, "url": url, "file": rel, "title": title,
            "privacy": privacy, "channel": ch["id"], "uploaded": time.time()})
        projects.save_project(proj)
        return {"video_id": vid, "url": url, "privacy": privacy}

    return jobs.submit("youtube_upload", task)
