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


def auth_url(cid: str, reconnect: bool = False) -> str:
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

    return jobs.submit("youtube_upload", task, pid=pid)


# =====================================================================
# In-app YouTube control center — manage a connected account's channel
# WITHOUT a browser: list channels, edit branding/banner, edit videos.
# (Creating a channel and setting the avatar are NOT in the API — those
# stay one-time website steps; everything here is API-supported.)
# =====================================================================

def _yt_creds(cid: str) -> Dict:
    ch = channels.get(cid)
    yt = (ch or {}).get("youtube") or {}
    if not (yt.get("client_id") and yt.get("refresh_token")):
        raise ValueError("This channel isn't connected to YouTube yet — Connect first.")
    return yt


def _authed_json(yt: Dict, method: str, url: str, *, token: Optional[str] = None,
                 params: Optional[Dict] = None, body: Optional[Dict] = None) -> Dict:
    """One authenticated JSON call to the Data API. Returns parsed JSON ({} on 204)."""
    token = token or _access_token(yt)
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_api_error(exc)) from exc


def _strip_readonly_image(bs: Dict) -> None:
    """channels.update rejects the computed banner*ImageUrl fields — keep only
    the writable bannerExternalUrl so a branding round-trip doesn't 400."""
    img = bs.get("image")
    if isinstance(img, dict):
        ext = img.get("bannerExternalUrl")
        if ext:
            bs["image"] = {"bannerExternalUrl": ext}
        else:
            bs.pop("image", None)


def list_my_channels(cid: str) -> Dict:
    """The YouTube channel(s) this account manages — id, title, avatar, banner,
    description, keywords, stats. Read-only snapshot for the control center."""
    yt = _yt_creds(cid)
    api = config.YOUTUBE["api_url"]
    data = _authed_json(yt, "GET", f"{api}/channels", params={
        "part": "snippet,statistics,brandingSettings", "mine": "true", "maxResults": 50})
    out = []
    for it in data.get("items", []):
        sn = it.get("snippet", {}) or {}
        st = it.get("statistics", {}) or {}
        bch = (it.get("brandingSettings", {}) or {}).get("channel", {}) or {}
        img = (it.get("brandingSettings", {}) or {}).get("image", {}) or {}
        thumbs = sn.get("thumbnails", {}) or {}
        out.append({
            "id": it["id"], "title": sn.get("title"),
            "custom_url": sn.get("customUrl"),
            "description": bch.get("description") or sn.get("description") or "",
            "keywords": bch.get("keywords", ""), "country": bch.get("country", ""),
            "avatar": (thumbs.get("high") or thumbs.get("medium")
                       or thumbs.get("default") or {}).get("url"),
            "banner": img.get("bannerExternalUrl"),
            "subs": st.get("subscriberCount"), "views": st.get("viewCount"),
            "videos": st.get("videoCount"),
        })
    return {"channels": out}


def update_branding(cid: str, patch: Dict) -> Dict:
    """Update description / keywords / country (channels.update brandingSettings).
    Title is sent if provided but Google usually ignores API title edits — no
    promise it sticks (rename on the website if it doesn't)."""
    yt = _yt_creds(cid)
    api = config.YOUTUBE["api_url"]
    token = _access_token(yt)
    cur = _authed_json(yt, "GET", f"{api}/channels", token=token,
                       params={"part": "brandingSettings", "mine": "true"})
    items = cur.get("items", [])
    if not items:
        raise ValueError("No channel found on this account.")
    ch0 = items[0]
    bs = ch0.get("brandingSettings", {}) or {}
    _strip_readonly_image(bs)
    bch = bs.setdefault("channel", {})
    for k_in, k_api in (("description", "description"), ("keywords", "keywords"),
                        ("country", "country"), ("title", "title"),
                        ("default_language", "defaultLanguage")):
        if patch.get(k_in) is not None:
            bch[k_api] = patch[k_in]
    _authed_json(yt, "PUT", f"{api}/channels", token=token,
                 params={"part": "brandingSettings"},
                 body={"id": ch0["id"], "brandingSettings": bs})
    return {"updated": True, "channel_id": ch0["id"],
            "title_note": "title edits via API are often ignored by Google"
                          if patch.get("title") is not None else None}


def set_banner(cid: str, image_bytes: bytes, content_type: str = "image/png") -> Dict:
    """Upload + set the channel banner (channelBanners.insert then channels.update).
    Best source: 2048x1152 px (the safe text area is ~1235x338)."""
    yt = _yt_creds(cid)
    token = _access_token(yt)
    req = urllib.request.Request(
        config.YOUTUBE["banner_url"], data=image_bytes, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": content_type or "image/png"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            up = json.load(r)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_api_error(exc)) from exc
    url = up.get("url")
    if not url:
        raise RuntimeError("Banner upload returned no url.")
    api = config.YOUTUBE["api_url"]
    cur = _authed_json(yt, "GET", f"{api}/channels", token=token,
                       params={"part": "brandingSettings", "mine": "true"})
    ch0 = cur["items"][0]
    bs = ch0.get("brandingSettings", {}) or {}
    _strip_readonly_image(bs)
    bs.setdefault("image", {})["bannerExternalUrl"] = url
    _authed_json(yt, "PUT", f"{api}/channels", token=token,
                 params={"part": "brandingSettings"},
                 body={"id": ch0["id"], "brandingSettings": bs})
    return {"banner": url}


def update_video(cid: str, video_id: str, patch: Dict) -> Dict:
    """Edit an uploaded video's title/description/tags/privacy (videos.update).
    Merges onto the current snippet+status (categoryId is required on update)."""
    yt = _yt_creds(cid)
    api = config.YOUTUBE["api_url"]
    token = _access_token(yt)
    cur = _authed_json(yt, "GET", f"{api}/videos", token=token,
                       params={"part": "snippet,status", "id": video_id})
    items = cur.get("items", [])
    if not items:
        raise ValueError("Video not found on this channel.")
    v = items[0]
    sn = v.get("snippet", {}) or {}
    stt = v.get("status", {}) or {}
    if patch.get("title") is not None:
        sn["title"] = str(patch["title"])[:100]
    if patch.get("description") is not None:
        sn["description"] = str(patch["description"])[:5000]
    if patch.get("tags") is not None:
        sn["tags"] = list(patch["tags"])[:60]
    if patch.get("privacy") is not None:
        stt["privacyStatus"] = patch["privacy"]
    _authed_json(yt, "PUT", f"{api}/videos", token=token,
                 params={"part": "snippet,status"},
                 body={"id": video_id, "snippet": sn, "status": stt})
    return {"updated": True, "video_id": video_id, "privacy": stt.get("privacyStatus")}
