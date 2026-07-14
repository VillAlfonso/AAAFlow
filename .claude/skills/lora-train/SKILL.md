---
name: lora-train
description: Train a Wan 2.2 style LoRA from a reference channel's footage without repeating the traps that cost us hours. Load before building any dataset, writing captions, or launching training.
---

# Training a Wan style LoRA (hard-won recipe)

Everything here was paid for in GPU hours on 2026-07-14. Follow it.

## THE ONE RULE OF CAPTIONS

**Whatever you DESCRIBE becomes detachable. Whatever you leave UNDESCRIBED
gets baked into the trigger.**

That single sentence explains both of our failures:

1. v1 captions described CONTENT only ("a man at a podium"). The look was
   never in words, so nothing bound the style to the trigger. Useless LoRA.
2. v2 captions described the style but never mentioned that 214 of 225
   training clips had **burned-in caption text** on screen. So "3d mannequin
   documentary" silently came to MEAN "…with letters on screen", and the
   model painted gibberish glyphs into every render.

So: caption the style you WANT (trigger + style clause), AND caption the
artifacts you want to be able to REMOVE (burned text, watermarks, letterbox
bars, channel logos). Naming an artifact is what makes a negative prompt
able to strip it later.

Caption shape:

    <TRIGGER>, <style clause for this clip's media class>, <content>. <camera>.
    (+ ", burned-in caption text overlay" when the clip HAS on-screen text)

## Dataset

- Cut clips at **detected shot boundaries** (`app/lora_dataset.py`), 2-4 s,
  skipping ~0.3 s after each cut. Never blind fixed-length slices: a clip
  that spans a cut teaches the model that video teleports.
- 200+ clips is plenty for a style. Low res is fine (384x216 buckets).
- Label each clip by its OWN media class from the techniques pass, so
  archival footage is never captioned as a 3D reconstruction.
- **Measure text contamination before training**: count clips whose tiles
  report text (`techniques.tiles[].text` != "none"). If most of the set has
  burned text, you MUST caption it (see above) or the glyphs are inherited.
- Strip the VLM's boilerplate opener ("The documentary frame is a…"): it
  teaches nothing and its "document" substring wrecks keyword matching.

## Training (16 GB card)

Base weights must be **fp16 or fp8_e4m3fn (non-scaled)** — musubi cannot
train from ComfyUI's `fp8_scaled` files, and ComfyUI's umt5 encoder is
scaled too (its `scale_weight` tensors make garbage embeddings). Get the
official `models_t5_umt5-xxl-enc-bf16.pth`.

Working command: `trainers/train_fern_lora.sh` (and `_resume.sh`). Key flags:

- `--mixed_precision fp16` (fp16 DiT *demands* fp16, it asserts otherwise)
- `--sdpa` (Windows needs an explicit attention backend or it hard-errors)
- `--fp8_base --blocks_to_swap 24` (fits 14B in 16 GB; makes it PCIe-bound,
  so the GPU stays quiet at ~46 W — that is normal, not a stall)
- `--max_data_loader_n_workers 0` — **non-negotiable on Windows.** With
  workers on, training deadlocks at an exact epoch boundary (GPU 0%, VRAM
  held, zero CPU). We lost 3.4 h to this.
- `--save_every_n_epochs 1` so a hang can never cost more than one epoch.
- Train the **low-noise expert only** for style; ~5 epochs, dim 16, lr 3e-4.
  Roughly 10 s/step, 426 steps/epoch on 225 clips.
- Rebuild the **text-encoder cache** after ANY caption edit (latent cache
  can stay: `rm cache/*_te.safetensors`).

## After training

- Copy the LoRA into `ComfyUI/models/loras/`, register it on the channel as
  `defaults.wan_loras: [{file, strength, experts: "low"}]`.
- **A/B test one clip before producing 40.** Same prompt, LoRA vs no LoRA.
- Strength 0.85 works; the style still reads at 0.6.
- The engine appends `config.WAN["negative_text"]` to EVERY render (Wan does
  content, never text) and the **glyph guard** (`animate._has_glyphs`) asks
  the local VLM whether a finished clip contains letters, re-rolling the seed
  if so. Never disable these for a LoRA trained on caption-heavy footage.

## Legality

Reference-footage LoRAs were user-approved on 2026-07-14 (risk disclosed:
gray zone; monetization carries reused-content risk). Clips never ship in a
video. Channels stay inspired-by: never the reference's name or branding.
