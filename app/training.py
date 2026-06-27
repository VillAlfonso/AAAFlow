"""LoRA training orchestration for the Training page.

Lists datasets under ``training/<base>/<name>/dataset``, starts a training run as
a subprocess (reusing ``trainers/train_krea2_lora.py``), and exposes the live log
+ parsed progress so the UI can show a terminal-style view with a progress bar.

Only one run at a time (the GPU does one anyway). krea2 is wired today; other
bases report ``trainable: false`` until their trainer is set up.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import config

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
BASES = ["krea2", "flux", "sdxl", "sd15"]

TRAINERS_DIR = config.BASE_DIR / "trainers"
TRAIN_SCRIPT = TRAINERS_DIR / "train_krea2_lora.py"
AAAFLOW_PY = config.BASE_DIR / ".venv" / "Scripts" / "python.exe"
KREA2_RAW = TRAINERS_DIR / "weights" / "krea2_raw.safetensors"
KREA2_TE = TRAINERS_DIR / "weights" / "qwen3vl_4b_bf16.safetensors"
MUSUBI_PY = TRAINERS_DIR / "musubi-tuner" / ".venv" / "Scripts" / "python.exe"
ACTIVE_JSON = config.TRAINING_RUNS_DIR / "active.json"

_lock = threading.Lock()
_run: Optional[Dict] = None          # active/last run; holds the Popen handle


def _krea2_ready() -> bool:
    return KREA2_RAW.exists() and KREA2_TE.exists() and MUSUBI_PY.exists()


def _base_ready(base: str) -> bool:
    return base == "krea2" and _krea2_ready()


def _krea2_proc_running() -> bool:
    """True if any krea2 training process is alive (covers CLI-started runs too),
    so we never launch a second one onto the GPU."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
             "Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=15).stdout or ""
        return "krea2_train_network" in out
    except Exception:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def _active() -> Optional[Dict]:
    """The active/last run: in-memory if this server started it, else the persisted
    record (so the Training page keeps working across server restarts)."""
    if _run is not None:
        return _run
    try:
        if ACTIVE_JSON.exists():
            return json.loads(ACTIVE_JSON.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _run_alive(a: Dict) -> bool:
    proc = a.get("proc")
    if proc is not None:
        return proc.poll() is None
    return _pid_alive(int(a.get("pid", -1)))


def list_datasets() -> List[Dict]:
    """Scan training/<base>/<name>/dataset and summarize each."""
    out: List[Dict] = []
    for base in BASES:
        bdir = config.TRAINING_DIR / base
        if not bdir.is_dir():
            continue
        for d in sorted(p for p in bdir.iterdir() if p.is_dir()):
            ds = d / "dataset"
            if not ds.is_dir():
                continue
            imgs = [p for p in ds.iterdir() if p.suffix.lower() in IMG_EXT]
            caps = [p for p in ds.iterdir() if p.suffix.lower() == ".txt"]
            outdir = d / "output"
            trained = sorted(outdir.glob("*.safetensors")) if outdir.is_dir() else []
            out.append({
                "base": base, "name": d.name, "images": len(imgs),
                "captions": len(caps), "trained": [p.name for p in trained],
                "trainable": _base_ready(base),
            })
    return out


def status() -> Dict:
    a = _active()
    s = {"krea2_ready": _krea2_ready(), "active": False, "run": None}
    if a:
        alive = _run_alive(a)
        if alive:
            st = "running"
        else:
            name, base = a.get("name", ""), a.get("base", "krea2")
            outdir = config.TRAINING_DIR / base / name / "output"
            done = outdir.is_dir() and any(outdir.glob(f"{name}*.safetensors"))
            st = "done" if done else "ended"
        s["active"] = alive
        s["run"] = {
            "id": a.get("id"), "base": a.get("base"), "name": a.get("name"),
            "trigger": a.get("trigger"), "params": a.get("params"),
            "started": a.get("started"), "status": st,
            "progress": _parse_progress(a.get("log_path", "")),
        }
    return s


def _parse_progress(log_path: str) -> Dict:
    try:
        raw = Path(log_path).read_bytes().decode("utf-8", errors="replace")
    except Exception:
        return {}
    raw = raw.replace("\r", "\n")
    step = total = epoch = ep_total = None
    loss = rate = None
    for m in re.finditer(r"steps:\s*\d+%[^|]*\|\s*(\d+)/(\d+)\s*\[([^\]]*)\]", raw):
        step, total = int(m.group(1)), int(m.group(2))
        inside = m.group(3)
        rm = re.search(r"([\d.]+)s/it", inside) or re.search(r"([\d.]+)it/s", inside)
        if rm:
            rate = rm.group(0)
    for m in re.finditer(r"epoch\s*(\d+)\s*/\s*(\d+)", raw):
        epoch, ep_total = int(m.group(1)), int(m.group(2))
    for m in re.finditer(r"(?:avr_)?loss[=:]\s*([\d.]+)", raw):
        loss = float(m.group(1))
    pct = round(100 * step / total, 1) if step and total else None
    return {"step": step, "total": total, "pct": pct, "epoch": epoch,
            "epoch_total": ep_total, "loss": loss, "rate": rate}


def start(base: str, name: str, trigger: str = "", epochs: int = 12,
          dim: int = 32, blocks_to_swap: int = 24, autocaption: bool = True) -> str:
    global _run
    with _lock:
        if _run is not None and _run["proc"].poll() is None:
            raise ValueError("A training run is already in progress.")
        if _krea2_proc_running():
            raise ValueError("A training run is already in progress on the GPU.")
        base = (base or "krea2").strip()
        name = (name or "").strip()
        if not name:
            raise ValueError("Pick a dataset.")
        if not _base_ready(base):
            raise ValueError(f"Training for '{base}' isn't set up yet (krea2 only for now).")
        ds = config.TRAINING_DIR / base / name / "dataset"
        imgs = [p for p in ds.iterdir() if p.suffix.lower() in IMG_EXT] if ds.is_dir() else []
        if not imgs:
            raise ValueError(f"No images in {ds}")

        rid = time.strftime("%Y%m%d_%H%M%S") + "_" + re.sub(r"[^A-Za-z0-9_-]", "", name)
        log_path = config.TRAINING_RUNS_DIR / f"{rid}.log"
        cmd = [str(AAAFLOW_PY), str(TRAIN_SCRIPT), "--name", name,
               "--trigger", (trigger or name), "--epochs", str(int(epochs)),
               "--dim", str(int(dim)), "--blocks-to-swap", str(int(blocks_to_swap))]
        if autocaption:
            cmd.append("--autocaption")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        lf = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                env=env, cwd=str(config.BASE_DIR))
        started = time.time()
        _run = {"id": rid, "base": base, "name": name, "trigger": trigger or name,
                "params": {"epochs": epochs, "dim": dim, "blocks_to_swap": blocks_to_swap},
                "proc": proc, "log_path": str(log_path), "_lf": lf,
                "started": started, "status": "running"}
        ACTIVE_JSON.write_text(json.dumps({
            "id": rid, "base": base, "name": name, "trigger": trigger or name,
            "params": {"epochs": epochs, "dim": dim, "blocks_to_swap": blocks_to_swap},
            "log_path": str(log_path), "pid": proc.pid, "started": started,
        }), encoding="utf-8")
        return rid


def get_log(tail_lines: int = 160) -> Dict:
    a = _active()
    if not a:
        return {"text": "", "status": "idle"}
    p = Path(a.get("log_path", ""))
    if not p.exists():
        return {"text": "", "status": "running" if _run_alive(a) else "ended"}
    raw = p.read_bytes().decode("utf-8", errors="replace")
    # collapse carriage-return progress redraws to the last state per line
    lines = []
    for ln in raw.replace("\r\n", "\n").split("\n"):
        lines.append(ln.split("\r")[-1] if "\r" in ln else ln)
    st = "running" if _run_alive(a) else "ended"
    return {"text": "\n".join(lines[-tail_lines:]).strip(), "status": st}


def stop() -> bool:
    a = _active()
    if a and _run_alive(a):
        pid = a["proc"].pid if a.get("proc") is not None else a.get("pid")
        try:  # kill the whole tree (runner -> accelerate -> training child)
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        except Exception:
            pass
        return True
    return False
