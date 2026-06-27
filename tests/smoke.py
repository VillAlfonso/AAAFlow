"""Standalone smoke test: download a model, synthesize a line, measure speed.

Usage:  python tests/smoke.py 0.6B   (or 1.7B)
Prints load/download time and the real-time factor (RTF) of synthesis.
"""
import sys
import time

# importing app.config sets HF_HOME to ./models
from app import config  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from qwen_tts import Qwen3TTSModel  # noqa: E402

SIZE = sys.argv[1] if len(sys.argv) > 1 else "0.6B"
repo = config.MODEL_REPOS[SIZE]["custom_voice"]

device = "cuda:0" if torch.cuda.is_available() else "cpu"
dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
print(f"[smoke] size={SIZE} repo={repo}", flush=True)
print(f"[smoke] torch={torch.__version__} device={device} dtype={dtype} "
      f"cuda={torch.cuda.is_available()}", flush=True)

t0 = time.time()
model = Qwen3TTSModel.from_pretrained(
    repo, device_map=device, dtype=dtype, attn_implementation=None)
t1 = time.time()
print(f"[smoke] load+download: {t1 - t0:.1f}s", flush=True)

text = ("Hey everyone, welcome back to the channel. Today we are trying out a "
        "completely local text to speech system, running right here on my own machine.")

t2 = time.time()
wavs, sr = model.generate_custom_voice(
    text=text, speaker="Ryan", language="English")
t3 = time.time()

dur = len(wavs[0]) / sr
out = config.OUTPUTS_DIR / f"smoke_{SIZE}.wav"
sf.write(str(out), np.asarray(wavs[0], dtype=np.float32), sr)

print(f"[smoke] synth: {t3 - t2:.1f}s  audio: {dur:.1f}s  "
      f"RTF: {(t3 - t2) / max(dur, 0.01):.2f}x  sr={sr}", flush=True)
print(f"[smoke] wrote {out}", flush=True)
print("[smoke] OK", flush=True)
