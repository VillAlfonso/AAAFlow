# FLUX.1 LoRAs

LoRAs for FLUX.1 (load via the diffusers FLUX path in AAAFlow's Images page).

Trainer: **ai-toolkit** or **kohya sd-scripts** (FLUX support).

Make one folder per LoRA:
```
flux/my-lora/
    dataset/   (images + optional .txt captions)
    output/
```

Heads-up: FLUX training needs the FLUX base weights (~24 GB) downloaded and is VRAM-heavy
on 16 GB (fp8 + low-VRAM mode). Free disk space first.
