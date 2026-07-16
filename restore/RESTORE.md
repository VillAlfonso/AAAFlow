# Restoring AAAFlow from nothing

You deleted the 198 GB folder. Here is how everything comes back. Three kinds of
data, three ways back:

| Kind | Size | Comes back by |
|---|---|---|
| Code + config | ~few MB | `git clone` (it's all on GitHub) |
| Models + Python libs | ~178 GB | **`restore.py`** — re-downloads from the real sources |
| Your irreplaceable data | ~12 GB | **your own backup** (nothing else can restore it) |

`restore.py` is the "pip install for the whole studio". It reads `deps.lock.json`
(the same HuggingFace repos the app itself uses) and fetches every model back.

## The 4 steps

```powershell
# 1. Code back
git clone https://github.com/VillAlfonso/AAAFlow C:\AAAFlow
cd C:\AAAFlow

# 2. The Qwen3-TTS engine is a broken gitlink — clone it by hand
git clone https://github.com/QwenLM/Qwen3-TTS third_party/Qwen3-TTS
#    then copy your patched qwen_tts/inference/qwen3_tts_model.py from backup over it

# 3. Everything re-downloadable: libraries, then model weights (~178 GB, slow)
python restore\restore.py --python
python restore\restore.py --models
#    (or just `python restore\restore.py` to do both)

# 4. Your 12 GB backup: copy these back from Google Drive
#    data/secrets/ , data/channels/*/projects/*/{video,audio}/ , data/lora_datasets/*/out/
```

## Check without downloading

```powershell
python restore\restore.py --check
```
Lists every model file as `[ok]` or `[MISS]` and totals the GB to fetch. Safe,
read-only. Run it anytime to see how complete a machine is.

## Prove it's byte-exact

The **capsule** manifest (a SHA-256 fingerprint of the whole tree, ~10 MB) is the
final check — it doesn't hold data, it proves the data you restored is identical:

```powershell
python C:\Users\USER\showcase-kit\capsule.py C:\AAAFlow --verify C:\Users\USER\AAAFlow-capsule\manifest.jsonl.gz
# -> "verify: 220296 identical, 0 changed, 0 missing"
```

## What restore.py can and can't do

- **Can**: Wan 2.2 video models, umt5 encoder, Wan VAE, speed LoRAs (all pinned to
  Comfy-Org repos in `deps.lock.json`); pip-install every requirements set; on
  `--prefetch`, pull Whisper + the writer LLM up front instead of on first run.
- **Can't (by design)**: your OAuth tokens, finished renders, narration wavs, and
  trained LoRA weights — those never existed on any public server. They are the
  one thing you must back up before deleting. See `deps.lock.json` -> `irreplaceable`.
- **Verify-first**: the krea2 render weights (the image model) are named in config
  but their download URL isn't in code — they came from ComfyUI Manager. `--check`
  flags them; re-fetch via ComfyUI Manager's model browser.

## The honest limit on "one tiny file"

You cannot compress 198 GB of model weights and video into a small archive — that
data is already at maximum entropy (Shannon's source-coding theorem; 7-Zip would
give you 195 GB back). What *is* small is the studio's **identity**: this
`restore.py` + `deps.lock.json` (fetch recipe) + the capsule manifest (proof) +
your 12 GB backup = a complete, byte-exact rebuild. The bulk bytes are fetched
from where they already live, not stored twice.
