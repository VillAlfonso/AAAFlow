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
    return config.YOUTUBE.get("redirect_uri") or ("http://127.0.0.1:8000" + config.YOUTUBE["redirect_path"])


def _effective_youtube_creds(yt: Optional[Dict] = None) -> Dict:
    yt = dict(yt or {})
    env_cfg = config.YOUTUBE or {}
    if not yt.get("client_id"):
        yt["client_id"] = env_cfg.get("client_id", "")
    if not yt.get("client_secret"):
        yt["client_secret"] = env_cfg.get("client_secret", "")
    return yt


def auth_url(cid: str, reconnect: bool = False) -> str:
    ch = channels.get(cid)
    yt = _effective_youtube_creds((ch or {}).get("youtube") or {})
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
    yt = _effective_youtube_creds((ch or {}).get("youtube") or {})
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


def _probe_duration(path) -> float:
    import subprocess
    from pathlib import Path as _P
    probe = str(_P(config.FFMPEG).with_name("ffprobe.exe"))
    if not _P(probe).exists():
        probe = "ffprobe"
    r = subprocess.run([probe, "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, timeout=60)
    return float(r.stdout.strip().splitlines()[0])


def _probe_height(path) -> int:
    import subprocess
    from pathlib import Path as _P
    probe = str(_P(config.FFMPEG).with_name("ffprobe.exe"))
    if not _P(probe).exists():
        probe = "ffprobe"
    try:
        r = subprocess.run([probe, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=height", "-of", "csv=p=0",
                            str(path)], capture_output=True, text=True, timeout=60)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return 0


def _youtube_master(src, progress):
    """YouTube starves 1080p uploads of bitrate; the SAME video uploaded at
    1440p lands in a much better codec tier (user, 2026-07-10: "youtube is
    messing up the quality"). Flat art upscales cleanly with lanczos, so
    uploads default to a cached 2560x1440 master."""
    import subprocess
    from pathlib import Path as _P
    src = _P(src)
    if _probe_height(src) >= 1440:
        return src
    dst = src.with_name(src.stem + "_yt1440.mp4")
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        # trust the cache only if it is a WHOLE mp4 at a sane bitrate (a
        # cancelled build once left a moov-less 60 Mbps partial behind)
        try:
            dur = _probe_duration(dst)
            if dur > 1 and dst.stat().st_size / dur < 5.0e6:   # < ~40 Mbps
                return dst
        except Exception:  # noqa: BLE001
            pass
        dst.unlink(missing_ok=True)
    progress("Building the 1440p YouTube master (bitrate-tier trick)", 0.03)
    tmp = dst.with_name(dst.stem + ".part.mp4")
    head = [config.FFMPEG, "-y", "-i", str(src),
            "-vf", "scale=2560:1440:flags=lanczos",
            "-c:a", "copy", "-movflags", "+faststart"]
    # cq19 capped near YouTube's recommended 1440p rate: transparent on this
    # art, and the upload stays ~1.5-2 GB instead of 4+
    for vcodec in (["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                    "-cq", "19", "-b:v", "0", "-maxrate", "30M",
                    "-bufsize", "60M", "-pix_fmt", "yuv420p"],
                   ["-c:v", "libx264", "-preset", "medium", "-crf", "17",
                    "-maxrate", "30M", "-bufsize", "60M",
                    "-pix_fmt", "yuv420p"]):
        r = subprocess.run(head + vcodec + [str(tmp)], capture_output=True,
                           timeout=3600)
        if r.returncode == 0 and tmp.exists():
            tmp.replace(dst)
            return dst
    tmp.unlink(missing_ok=True)
    raise RuntimeError("1440p master encode failed")


def _publish_at_rfc3339(v) -> Optional[str]:
    """Local 'YYYY-MM-DDTHH:MM' (the datetime-local input) -> RFC3339 UTC."""
    v = (v or "").strip()
    if not v:
        return None
    import datetime as _dt
    t = _dt.datetime.fromisoformat(v)
    if t.tzinfo is None:
        t = t.astimezone()                      # interpret as local time
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_THUMB_LIMIT = 2 * 1024 * 1024          # YouTube's hard cap for custom thumbnails


def _thumb_payload(pdir) -> Optional[tuple]:
    """The project's chosen thumbnail as (bytes, mime). Recodes to JPEG when
    the PNG would blow YouTube's 2 MB cap."""
    src = pdir / "thumbnail.png"
    if not src.exists():
        tdir = pdir / "video" / "thumbs"
        cand = sorted(tdir.glob("*.png"), key=lambda f: f.stat().st_mtime) \
            if tdir.is_dir() else []
        if not cand:
            return None
        src = cand[-1]
    data = src.read_bytes()
    if len(data) <= _THUMB_LIMIT:
        return data, "image/png"
    try:
        from io import BytesIO
        from PIL import Image
        im = Image.open(src).convert("RGB")
        for q in (92, 85, 78, 70):
            buf = BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True)
            if buf.tell() <= _THUMB_LIMIT:
                return buf.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 - fall through to "no payload"
        pass
    return None


def _push_thumb(token: str, vid: str, pdir) -> str:
    """thumbnails/set for one video; '' on success, a readable error on failure."""
    payload = _thumb_payload(pdir)
    if not payload:
        return "no thumbnail.png in the project (generate SEO or pick a variant first)"
    data, mime = payload
    req = urllib.request.Request(
        f"{config.YOUTUBE['thumb_url']}?videoId={vid}&uploadType=media",
        data=data, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": mime})
    try:
        urllib.request.urlopen(req, timeout=120).read()
        return ""
    except urllib.error.HTTPError as exc:
        err = _api_error(exc)
        if "thumbnail" in err.lower() and "permission" in err.lower():
            err += (" | YouTube unlocks custom thumbnails once the channel is "
                    "phone-verified at youtube.com/verify (one time, instant); "
                    "verify, then hit Retry thumbnail on the upload row.")
        return err


def _safe_tags(ts):
    """YouTube rejects the whole request (400 invalidTags) when the tag
    LIST passes ~500 characters total (spaces cost 2 extra for implied
    quotes) or any tag is too long. Keep the best-first prefix that fits."""
    import re as _re
    out, total = [], 0
    for t in ts or []:
        t = _re.sub(r"[<>]", "", str(t)).strip()
        if not t or len(t) > 90:
            continue
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if total + cost > 470:
            break
        out.append(t)
        total += cost
    return out


_STATUS_CACHE: Dict[str, tuple] = {}   # pid -> (ts, result); protects API quota


def video_status(pid: str, max_age: float = 20.0) -> Dict:
    """What YouTube ACTUALLY has right now for every upload row, in ONE
    batched videos.list call: live title, privacy, processing state, and
    whether the video still exists. The Publish page polls this so app-side
    state and YouTube-side truth stay visibly in sync."""
    now = time.time()
    hit = _STATUS_CACHE.get(pid)
    if hit and now - hit[0] < max_age:
        return hit[1]
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    ch = channels.get(project.get("channel"))
    yt = _effective_youtube_creds((ch or {}).get("youtube") or {})
    ids = [u.get("video_id") for u in (project.get("uploads") or [])
           if u.get("video_id")]
    res = {"videos": {}, "checked": now}
    if ids and yt.get("client_id") and yt.get("refresh_token"):
        token = _access_token(yt)
        data = _authed_json(yt, "GET", f"{config.YOUTUBE['api_url']}/videos",
                            token=token,
                            params={"part": "snippet,status,processingDetails",
                                    "id": ",".join(ids[:50])})
        for it in data.get("items", []):
            sn = it.get("snippet") or {}
            stt = it.get("status") or {}
            pd = it.get("processingDetails") or {}
            res["videos"][it["id"]] = {
                "title": sn.get("title"),
                "privacy": stt.get("privacyStatus"),
                "publish_at": stt.get("publishAt"),
                "processing": pd.get("processingStatus"),   # processing | succeeded
            }
        for vid in ids:
            if vid not in res["videos"]:
                res["videos"][vid] = {"missing": True}      # deleted on YouTube
    _STATUS_CACHE[pid] = (now, res)
    return res


def sync_seo(pid: str, video_id: str = "") -> Dict:
    """Push the project's CURRENT saved SEO (title/description/tags) onto an
    already-uploaded video. Re-packaging after an upload rewrites the SEO,
    which used to leave the live video on stale copy with no way to catch up
    short of re-uploading."""
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    cid = project.get("channel")
    if not cid:
        raise ValueError("This project has no channel.")
    ups = project.get("uploads") or []
    vid = video_id or (ups[0].get("video_id") if ups else "")
    if not vid:
        raise ValueError("No uploaded video to sync.")
    seo = project.get("seo") or {}
    title = ((seo.get("titles") or [None])[0]
             or project.get("video", {}).get("title") or project.get("name"))[:100]
    update_video(cid, vid, {
        "title": title,
        "description": (seo.get("description") or "")[:4900],
        "tags": _safe_tags(seo.get("tags") or []),
    })
    for u in ups:
        if u.get("video_id") == vid:
            u["title"] = title
            u["seo_synced"] = time.time()
    projects.save_project(project)
    _STATUS_CACHE.pop(pid, None)
    return {"video_id": vid, "title": title, "synced": True}


def set_thumbnail(pid: str, video_id: str = "") -> Dict:
    """Set (or RETRY) the custom thumbnail on an already-uploaded video: the
    fix-up path for uploads that 403'd before the channel had the
    custom-thumbnail feature (phone verification)."""
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    ch = channels.get(project.get("channel"))
    if not ch:
        raise ValueError("This project has no channel.")
    yt = _effective_youtube_creds(ch.get("youtube") or {})
    if not (yt.get("client_id") and yt.get("refresh_token")):
        raise ValueError("Channel isn't connected to YouTube yet.")
    ups = project.get("uploads") or []
    vid = video_id or (ups[0].get("video_id") if ups else "")
    if not vid:
        raise ValueError("No uploaded video to set a thumbnail on.")
    err = _push_thumb(_access_token(yt), vid, projects.project_dir(pid))
    for u in ups:
        if u.get("video_id") == vid:
            u["thumbnail"] = "set" if not err else f"failed: {err}"
    projects.save_project(project)
    _STATUS_CACHE.pop(pid, None)
    if err:
        raise RuntimeError(err)
    return {"video_id": vid, "thumbnail": "set"}


def submit_upload(pid: str, opts: Optional[Dict] = None) -> str:
    """Upload a project render (default: newest final) to its channel's YouTube.

    opts: file (project-relative mp4), title, description, tags, privacy,
    thumbnail (bool, default True), master (bool, default True: upload a
    1440p upscale), publish_at (local datetime: YouTube flips the private
    upload public at that time).
    """
    opts = opts or {}
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    ch = channels.get(project.get("channel"))
    if not ch:
        raise ValueError("This project has no channel — uploads are per-channel.")
    yt = _effective_youtube_creds(ch.get("youtube") or {})
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

    tags = _safe_tags(opts.get("tags") or seo.get("tags") or [])
    privacy = opts.get("privacy") or yt.get("privacy") or "private"
    category = str(yt.get("category_id") or "27")
    publish_at = _publish_at_rfc3339(opts.get("publish_at")
                                     or seo.get("publish_at") or "")
    want_master = opts.get("master", True)

    def task(progress) -> Dict:
        up_src = src
        if want_master:
            try:
                up_src = _youtube_master(src, progress)
            except Exception as exc:  # noqa: BLE001 - original still uploads
                progress(f"1440p master skipped ({exc})", 0.03)
        progress("Refreshing access token", 0.04)
        token = _access_token(yt)
        status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
        if publish_at:
            # the YouTube way: upload PRIVATE with publishAt; YouTube flips it
            # public at that moment (needs a verified OAuth app to stick)
            status["privacyStatus"] = "private"
            status["publishAt"] = publish_at
        meta = {
            "snippet": {"title": title, "description": description,
                        "tags": tags[:60], "categoryId": category},
            "status": status,
        }
        progress("Starting resumable upload", 0.05)
        size = up_src.stat().st_size
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
        with open(up_src, "rb") as f:
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

        thumb_state = "skipped"
        if opts.get("thumbnail", True):
            progress("Setting thumbnail", 0.93)
            terr = _push_thumb(token, vid, pdir)
            thumb_state = "set" if not terr else f"failed: {terr}"
            if terr:
                print(f"[youtube] thumbnail set failed: {terr}")

        url = f"https://youtu.be/{vid}"
        proj = projects.get_project(pid)
        proj.setdefault("uploads", []).insert(0, {
            "video_id": vid, "url": url, "file": rel, "title": title,
            "privacy": ("scheduled" if publish_at else privacy),
            "publish_at": publish_at,
            "master_1440": str(up_src) != str(src),
            "thumbnail": thumb_state,
            "channel": ch["id"], "uploaded": time.time()})
        projects.save_project(proj)
        return {"video_id": vid, "url": url, "privacy": privacy,
                "thumbnail": thumb_state}

    return jobs.submit("youtube_upload", task, pid=pid)


# =====================================================================
# In-app YouTube control center — manage a connected account's channel
# WITHOUT a browser: list channels, edit branding/banner, edit videos.
# (Creating a channel and setting the avatar are NOT in the API — those
# stay one-time website steps; everything here is API-supported.)
# =====================================================================

def _yt_creds(cid: str) -> Dict:
    ch = channels.get(cid)
    yt = _effective_youtube_creds((ch or {}).get("youtube") or {})
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
