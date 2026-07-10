"""A tiny single-worker background job queue with progress reporting.

One worker thread processes jobs sequentially, which conveniently serializes
model inference (a single loaded model is not thread-safe). The frontend polls
GET /api/jobs/{id} for stage + progress while a job runs.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, Optional

ProgressFn = Callable[[str, float], None]


class JobCancelled(Exception):
    """Raised inside a running job's progress callback once it's been cancelled,
    so the work stops cooperatively at the next progress checkpoint."""


_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_q: "queue.Queue[str]" = queue.Queue()
_fns: Dict[str, Callable[[ProgressFn], Dict]] = {}
_worker: Optional[threading.Thread] = None


def _update(jid: str, **kw: Any) -> None:
    with _lock:
        if jid in _jobs:
            _jobs[jid].update(kw)


def submit(kind: str, fn: Callable[[ProgressFn], Dict],
           pid: Optional[str] = None) -> str:
    jid = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[jid] = {
            "id": jid, "kind": kind, "pid": pid, "status": "queued",
            "stage": "queued", "progress": 0.0, "created": time.time(),
            "result": None, "error": None, "cancel": False,
        }
    _fns[jid] = fn
    _q.put(jid)
    return jid


def cancel(jid: str) -> bool:
    """Request cancellation. A queued job is dropped immediately; a running one
    is flagged and stops at its next progress checkpoint (~1 scene)."""
    with _lock:
        j = _jobs.get(jid)
        if not j or j["status"] in ("done", "error", "cancelled"):
            return False
        j["cancel"] = True
        if j["status"] == "queued":
            j.update(status="cancelled", stage="cancelled", finished=time.time())
            _fns.pop(jid, None)
    return True


def active_for(pid: str) -> Optional[Dict]:
    """The newest queued/running job for a project — lets the UI reconnect to an
    in-flight build after a page switch or refresh (the 'dead spinner' fix)."""
    with _lock:
        cands = [j for j in _jobs.values()
                 if j.get("pid") == pid and j["status"] in ("queued", "running")]
        return dict(max(cands, key=lambda x: x["created"])) if cands else None


def get_job(jid: str) -> Optional[Dict]:
    with _lock:
        j = _jobs.get(jid)
        return dict(j) if j else None


def _progress_for(jid: str) -> ProgressFn:
    def cb(stage: str, frac: float) -> None:
        with _lock:
            j = _jobs.get(jid)
            if j and j.get("cancel"):
                raise JobCancelled()
        _update(jid, stage=stage, progress=max(0.0, min(1.0, float(frac))))
    return cb


def _touch_gpu() -> None:
    try:
        from . import gpu
        gpu.touch()
    except Exception:  # noqa: BLE001
        pass


def _loop() -> None:
    while True:
        jid = _q.get()
        fn = _fns.pop(jid, None)
        if fn is None:
            _q.task_done()
            continue
        _touch_gpu()
        _update(jid, status="running", stage="starting", progress=0.01)
        try:
            result = fn(_progress_for(jid))
            _update(jid, status="done", stage="done", progress=1.0, result=result,
                    finished=time.time())
        except JobCancelled:
            _update(jid, status="cancelled", stage="cancelled",
                    finished=time.time())
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            _update(jid, status="error", stage="error",
                    error=f"{type(exc).__name__}: {exc}", finished=time.time())
            traceback.print_exc()
        finally:
            _q.task_done()
            _touch_gpu()
            _gc()


def _gc(max_age: float = 7200.0, keep: int = 60) -> None:
    """Drop old finished jobs so the dict doesn't grow forever.

    Age is measured from COMPLETION, not creation — a 2h+ images job used to
    be evicted the moment it finished, and the produce orchestrator polling it
    saw "vanished" (the Sodder 141-scene build, 2026-07-05)."""
    now = time.time()
    with _lock:
        done = [j for j in _jobs.values() if j["status"] in ("done", "error")]
        for j in done:
            if now - j.get("finished", j["created"]) > max_age:
                _jobs.pop(j["id"], None)
        if len(_jobs) > keep:
            for j in sorted(done, key=lambda x: x["created"])[: len(_jobs) - keep]:
                _jobs.pop(j["id"], None)


def start_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_loop, name="tts-worker", daemon=True)
        _worker.start()
