#!/usr/bin/env python3
"""restore.py -- the 'pip install for the whole studio'.

A git clone of AAAFlow restores only the code (~few MB). This script fetches
back the ~178 GB of gitignored models + Python deps from their real sources,
reading the recipe in deps.lock.json (the same HuggingFace repos the app itself
uses). What it CANNOT restore is your irreplaceable data (secrets, renders,
LoRAs) -- that comes from your own backup; the script just reminds you.

    python restore/restore.py --check     # what's present vs missing (read-only)
    python restore/restore.py --python     # pip install every requirements set
    python restore/restore.py --models     # download the pinned model weights
    python restore/restore.py              # python, then models (full restore)
    python restore/restore.py --prefetch   # also pull the on-first-run models now

Idempotent: skips any file already present at the right size (HuggingFace
metadata), so re-running after an interruption just resumes.
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent          # C:\AAAFlow
LOCK = json.loads((Path(__file__).parent / "deps.lock.json").read_text(encoding="utf-8"))
GiB = 2 ** 30


def human(g):  # gib float -> "14.0 GB"
    return f"{g:.2f} GB" if g < 10 else f"{g:.0f} GB"


def size_gib(p: Path):
    try:
        return p.stat().st_size / GiB
    except OSError:
        return None


# ---------------------------------------------------------------- check --------
def check():
    print("AAAFlow restore -- inventory (read-only)\n" + "=" * 52)
    present = missing = 0
    totmiss = 0.0
    groups = [("Model weights (auto-fetch)", LOCK["huggingface"], True),
              ("krea2 render stack (VERIFY source)", LOCK["verify_source"][0]["files"], False)]
    for title, items, is_hf in groups:
        print(f"\n{title}:")
        files = items if not is_hf else [i["dest"] for i in items]
        whys = [i.get("why", "") for i in items] if is_hf else [""] * len(files)
        gibs = [i.get("gib", 0) for i in items] if is_hf else [LOCK["verify_source"][0]["gib"] / len(files)] * len(files)
        for dest, why, gib in zip(files, whys, gibs):
            p = ROOT / dest
            have = size_gib(p)
            if have is not None:
                present += 1
                print(f"  [ok]   {Path(dest).name:52s} {human(have)}")
            else:
                missing += 1
                totmiss += gib
                print(f"  [MISS] {Path(dest).name:52s} ~{human(gib)}  {why}")
    print("\n" + "=" * 52)
    print(f"{present} present, {missing} missing (~{human(totmiss)} to fetch).")
    print("\nOn-first-run (not counted; download themselves when the app needs them):")
    for m in LOCK["auto_on_first_run"]:
        print(f"  ~ {m['name']:34s} ~{human(m['gib'])}")
    _reminders()


# ---------------------------------------------------------------- python -------
def do_python():
    print("Installing Python dependencies...\n" + "=" * 52)
    for step in LOCK["python"]:
        cwd = ROOT / step["cwd"]
        if not cwd.exists():
            print(f"  [skip] {step['name']}: {step['cwd']} not present")
            continue
        print(f"\n>>> {step['name']}  (in {step['cwd']})\n    {step['cmd']}")
        r = subprocess.run(step["cmd"], shell=True, cwd=str(cwd))
        if r.returncode != 0:
            print(f"  [warn] {step['name']} exited {r.returncode} -- continuing")
    print("\nPython deps done.")


# ---------------------------------------------------------------- models -------
def do_models(prefetch=False):
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url
    except ImportError:
        sys.exit("huggingface_hub missing -- run `python restore/restore.py --python` first.")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")   # fast parallel download
    items = LOCK["huggingface"]
    print(f"Fetching {len(items)} model files from HuggingFace...\n" + "=" * 52)
    for i, m in enumerate(items, 1):
        dest = ROOT / m["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            want = get_hf_file_metadata(hf_hub_url(m["repo"], m["file"])).size
        except Exception:                                     # noqa: BLE001
            want = None
        if dest.exists() and want and dest.stat().st_size == want:
            print(f"  [{i}/{len(items)}] {dest.name} present ✓")
            continue
        print(f"  [{i}/{len(items)}] downloading {dest.name} (~{human(m.get('gib', 0))}) from {m['repo']}")
        cached = hf_hub_download(m["repo"], m["file"])
        if not dest.exists() or os.path.getsize(cached) != dest.stat().st_size:
            shutil.copy2(cached, dest)                        # place into ComfyUI's tree
        try:
            os.remove(cached)                                 # single copy on a tight disk
        except OSError:
            pass
        print(f"        {dest.name} ready")
    if prefetch:
        print("\nPre-fetching on-first-run models...")
        for m in LOCK["auto_on_first_run"]:
            cmd = m.get("prefetch")
            if cmd:
                print(f"  {m['name']}...")
                subprocess.run(cmd, shell=True, cwd=str(ROOT))
    print("\nModel fetch done.")
    _reminders()


# ---------------------------------------------------------------- reminders ----
def _reminders():
    irr = LOCK["irreplaceable"]
    print("\n" + "!" * 52)
    print("RESTORE FROM YOUR OWN BACKUP (cannot be re-downloaded):")
    for p in irr["paths"]:
        print("  " + p)
    tts = ROOT / "third_party" / "Qwen3-TTS"
    if not (tts / "pyproject.toml").exists():
        print("\n[landmine] " + LOCK["landmine_qwen3tts"])
    print("\nVERIFY byte-exact when done:\n  " + LOCK["verify"])
    print("!" * 52)


def main():
    ap = argparse.ArgumentParser(description="Re-download AAAFlow's models + Python deps.")
    ap.add_argument("--check", action="store_true", help="report present/missing, download nothing")
    ap.add_argument("--python", action="store_true", help="pip install every requirements set")
    ap.add_argument("--models", action="store_true", help="download the pinned model weights")
    ap.add_argument("--prefetch", action="store_true", help="also pull on-first-run models (whisper/LLM)")
    a = ap.parse_args()
    if a.check:
        check(); return
    if not (a.python or a.models or a.prefetch):             # bare run = full restore
        do_python(); do_models(); return
    if a.python:
        do_python()
    if a.models or a.prefetch:
        do_models(prefetch=a.prefetch)


if __name__ == "__main__":
    main()
