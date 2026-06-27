# Stable Diffusion 1.5 LoRAs

LoRAs for SD 1.5 (load via the diffusers SD path in AAAFlow's Images page). You already
have the SD 1.5 base locally (`models/diffusion/v1-5-pruned-emaonly.safetensors`).

Trainer: **kohya_ss / sd-scripts**.

Make one folder per LoRA:
```
sd15/my-lora/
    dataset/   (images + optional .txt captions)
    output/
```

Easiest + fastest: base ~2 GB (already here), trains quickly on 16 GB at 512-768px.
Good for a first end-to-end test of the training pipeline.
