"""End-to-end verification of the three headline features on the real engine:
emotional control, voice cloning, and voice design. Loads one model at a time
(freeing each before the next) so it stays within RAM. Writes sample clips to
data/outputs so the results can be auditioned.
"""
import gc
import time
import traceback

from app import config
import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

OUT = config.OUTPUTS_DIR
REFS = config.REFS_DIR

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
DTYPE = torch.bfloat16 if torch.cuda.is_available() else torch.float32


def load(task):
    repo = config.MODEL_REPOS["1.7B"][task]
    return Qwen3TTSModel.from_pretrained(
        repo, device_map=DEVICE, dtype=DTYPE, attn_implementation=None)


def save(wav, sr, name):
    sf.write(str(OUT / name), np.asarray(wav, dtype=np.float32), sr)
    return len(wav) / sr


results = {}

# 1) EMOTIONAL CONTROL + make a reference clip for cloning ------------------
try:
    print("=== EMOTION (CustomVoice + instruct) ===", flush=True)
    m = load("custom_voice")
    t = time.time()
    wavs, sr = m.generate_custom_voice(
        text="I cannot believe we actually pulled this off, this is incredible!",
        speaker="Aiden", language="English",
        instruct="Speak in a very excited, high-energy tone.")
    dur = save(wavs[0], sr, "test_emotion_excited.wav")
    print(f"  excited: {dur:.1f}s in {time.time()-t:.0f}s", flush=True)

    wavs, sr = m.generate_custom_voice(
        text="I cannot believe we actually pulled this off, this is incredible!",
        speaker="Aiden", language="English",
        instruct="Speak in a calm, sad, subdued tone.")
    save(wavs[0], sr, "test_emotion_sad.wav")

    ref_text = ("The quick brown fox jumps over the lazy dog while the morning "
                "light spills across the quiet valley below.")
    wavs, sr = m.generate_custom_voice(text=ref_text, speaker="Ryan", language="English")
    ref_path = REFS / "selftest_ref.wav"
    sf.write(str(ref_path), np.asarray(wavs[0], dtype=np.float32), sr)
    print(f"  reference clip for cloning: {len(wavs[0])/sr:.1f}s", flush=True)
    results["emotion"] = "PASS"
    del m
    gc.collect()
except Exception as exc:
    results["emotion"] = f"FAIL: {exc!r}"
    traceback.print_exc()

# 2) VOICE CLONING (Base model, full round-trip) ----------------------------
try:
    print("=== CLONE (Base) ===", flush=True)
    mb = load("base")
    t = time.time()
    wavs, sr = mb.generate_voice_clone(
        text="And now the very same voice is reading a brand new sentence it never saw.",
        language="English", ref_audio=str(REFS / "selftest_ref.wav"), ref_text=ref_text)
    dur = save(wavs[0], sr, "test_clone.wav")
    print(f"  clone: {dur:.1f}s in {time.time()-t:.0f}s", flush=True)
    results["clone"] = "PASS"
    del mb
    gc.collect()
except Exception as exc:
    results["clone"] = f"FAIL: {exc!r}"
    traceback.print_exc()

# 3) VOICE DESIGN (VoiceDesign model) ---------------------------------------
try:
    print("=== DESIGN (VoiceDesign) ===", flush=True)
    md = load("voice_design")
    t = time.time()
    wavs, sr = md.generate_voice_design(
        text="Welcome back to the channel. Today, we go deeper than ever before.",
        instruct="A calm, warm middle-aged male documentary narrator with a deep, "
                 "resonant voice and measured, deliberate pacing.",
        language="English")
    dur = save(wavs[0], sr, "test_design.wav")
    print(f"  design: {dur:.1f}s in {time.time()-t:.0f}s", flush=True)
    results["design"] = "PASS"
    del md
    gc.collect()
except Exception as exc:
    results["design"] = f"FAIL: {exc!r}"
    traceback.print_exc()

print("\n==== FEATURE TEST RESULTS ====", flush=True)
for k, v in results.items():
    print(f"  {k:8s}: {v}", flush=True)
