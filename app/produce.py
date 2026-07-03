"""One-call production pipeline: voice → images → animate → assemble.

``submit_produce`` runs the whole storyboard-to-video chain as a sequence of
normal background jobs, coordinated by a lightweight thread (NOT a job itself
— the queue has a single worker, so a job waiting on jobs would deadlock).
Each stage is idempotent/"missing"-scoped, so a crashed or interrupted
production resumes by simply producing again. Status is polled at
GET /api/projects/{pid}/produce — one poll target for the entire pipeline
instead of babysitting four jobs.

Default plan (each part can be overridden or skipped):
  voice     "onetake" when the project has no narration track yet
  images    render missing stills (krea2 or whatever the project uses)
  animate   LTX clips for motion scenes that lack one (skipped when the
            assemble preset doesn't use clips)
  assemble  final render with the project's style preset
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from . import animate, assemble, config, effects, images, jobs, music, projects, storage, voiceover

_state: Dict[str, Dict] = {}
_lock = threading.Lock()


def status(pid: str) -> Optional[Dict]:
    with _lock:
        st = _state.get(pid)
        return dict(st) if st else None


def _set(pid: str, **kw):
    with _lock:
        _state.setdefault(pid, {}).update(kw)


def default_plan(project: Dict) -> Dict:
    settings = project.get("settings", {})
    preset = effects.get((settings.get("assemble", {}) or {}).get("preset")
                         or "cinematic")
    uses_clips = "clips" in (preset.get("sources") or [])
    engine = (settings.get("animate", {}) or {}).get("engine", "wan")
    return {
        "voice": "skip" if project.get("narration") else "onetake",
        "images": True,
        # channel music_vibe + no bed set yet + ACE installed → generate one
        "music": bool(settings.get("music_vibe")) and not settings.get("music")
                 and config.music_env_ready() and config.music_model_ready(),
        "animate": {"scope": "missing"} if (uses_clips and engine != "none") else False,
        "assemble": {},
    }


def submit_produce(pid: str, plan: Optional[Dict] = None) -> Dict:
    project = projects.get_project(pid)
    if not project:
        raise ValueError("Project not found.")
    cur = status(pid)
    if cur and cur.get("status") == "running":
        raise ValueError("A production is already running for this project.")
    plan = {**default_plan(project), **(plan or {})}

    stages = []
    if plan.get("voice") and plan["voice"] != "skip":
        stages.append("voice")
    if plan.get("images"):
        stages.append("images")
    if plan.get("music"):
        stages.append("music")      # before animate so the ACE sidecar can be freed
    if plan.get("animate"):
        stages.append("animate")
    if plan.get("assemble") is not False:
        stages.append("assemble")
    if not stages:
        raise ValueError("The plan skips every stage — nothing to do.")

    _set(pid, status="running", stage=stages[0], plan=plan, error=None,
         result=None, started=time.time(),
         stages=[{"name": s, "status": "pending", "job_id": None} for s in stages])

    def _submit_stage(name: str) -> str:
        proj = projects.get_project(pid)
        if name == "voice":
            if plan["voice"] == "scenes":
                return voiceover.submit_voiceover(pid, proj["settings"].get("voice") or {},
                                                  scope="missing")
            return voiceover.submit_onetake(pid, proj["settings"].get("voice") or {})
        if name == "images":
            icfg = dict(proj["settings"].get("image") or {})
            return images.submit_images(pid, icfg, scope="missing")
        if name == "music":
            vibe = (proj["settings"].get("music_vibe") or "").strip()
            return music.submit_music({
                "prompt": vibe + ", instrumental background bed, loopable, "
                                 "no vocals", "seconds": 75, "kind": "bgm"})
        if name == "animate":
            aopts = dict(plan["animate"]) if isinstance(plan["animate"], dict) else {}
            scope = aopts.pop("scope", "missing")
            return animate.submit_animate(pid, aopts, scope=scope)
        if name == "assemble":
            aopts = dict(plan["assemble"]) if isinstance(plan["assemble"], dict) else {}
            return assemble.submit_assemble(pid, aopts)
        raise ValueError(f"Unknown stage {name}")

    def _kill_ace_sidecar():
        """Free the music engine's VRAM before video work (no unload API)."""
        import re as _re
        import subprocess
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True,
                                 text=True, timeout=15).stdout
            for line in out.splitlines():
                if ":8765" in line and "LISTENING" in line:
                    m = _re.search(r"(\d+)\s*$", line)
                    if m:
                        subprocess.run(["taskkill", "/PID", m.group(1), "/F"],
                                       capture_output=True, timeout=15)
                        return
        except Exception:  # noqa: BLE001 — best-effort
            pass

    def _attach_music(jid: str):
        """Set the generated bed on the project (ducked, low, faded)."""
        j = jobs.get_job(jid) or {}
        files = (j.get("result") or {}).get("files") or {}
        f = files.get("wav") or next(iter(files.values()), None)
        if not f:
            return
        proj = projects.get_project(pid)
        proj["settings"]["music"] = {"file": f, "volume": 0.16, "duck": True,
                                     "fade": 1.5,
                                     "prompt": proj["settings"].get("music_vibe")}
        projects.save_project(proj)

    def _run():
        try:
            for i, name in enumerate(stages):
                with _lock:
                    entry = _state[pid]["stages"][i]
                try:
                    jid = _submit_stage(name)
                except ValueError as exc:
                    # "nothing to do" for an idempotent stage is success, not failure
                    msg = str(exc).lower()
                    if "no scenes" in msg or "nothing" in msg:
                        entry.update(status="skipped", detail=str(exc))
                        continue
                    raise
                entry.update(status="running", job_id=jid)
                _set(pid, stage=name, job_id=jid)
                while True:
                    j = jobs.get_job(jid)
                    if not j:
                        raise RuntimeError(f"{name} job vanished")
                    _set(pid, stage=f"{name}: {j.get('stage')}",
                         progress=j.get("progress"))
                    if j["status"] == "done":
                        entry.update(status="done")
                        if name == "music":
                            _attach_music(jid)
                            _kill_ace_sidecar()
                        if name == "assemble":
                            _set(pid, result=j.get("result"))
                        break
                    if j["status"] == "error":
                        raise RuntimeError(f"{name} failed: {j.get('error')}")
                    time.sleep(2)
            _set(pid, status="done", stage="done", progress=1.0)
        except Exception as exc:  # noqa: BLE001
            _set(pid, status="error", error=f"{type(exc).__name__}: {exc}")
        finally:
            storage.add_history({
                "id": storage.new_id(), "created": time.time(), "preview": False,
                "kind": "produce", "project": pid,
                "project_name": (projects.get_project(pid) or {}).get("name"),
                "text_preview": f"Production {'finished' if status(pid).get('status') == 'done' else 'FAILED'}"
                                f" ({' → '.join(stages)})",
            })

    threading.Thread(target=_run, name=f"produce-{pid}", daemon=True).start()
    return {"pid": pid, "stages": stages, "plan": plan}
