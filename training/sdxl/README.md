# SDXL LoRAs

LoRAs for SDXL (load via the diffusers SDXL path in AAAFlow's Images page).

Trainer: **kohya_ss / sd-scripts** (very well-supported).

Make one folder per LoRA:
```
sdxl/my-lora/
    dataset/   (images + optional .txt captions)
    output/
```

Moderate cost: SDXL base ~7 GB, trains comfortably on 16 GB at 1024px.
