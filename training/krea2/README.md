# krea2 LoRAs — Qwen-Image-class (ComfyUI)

LoRAs for the local **krea2** flat-cartoon model (`krea2_turbo_fp8_scaled`). These load
into the krea2 ComfyUI workflow (`LoraLoaderModelOnly`) and into AAAFlow's Images page,
so a custom style/character stays consistent across all your scenes.

Trainer: **musubi-tuner** (kohya) or **ai-toolkit** — both support Qwen-Image LoRA.

Make one folder per LoRA, e.g.:

```
krea2/my-cartoon-style/
    dataset/   (drop images + optional .txt captions)
    output/
```

Notes for 16 GB VRAM: krea2 is a ~20B base, so training uses fp8 + block-swapping
(low-VRAM mode) and takes a few hours. Keep datasets tight and on-style (20-40 images
for a style, fewer for a character).
