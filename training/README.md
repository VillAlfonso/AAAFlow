# AAAFlow — Custom LoRA training

Drop your training images in here and I'll caption, configure, and train a LoRA for
you on your RTX 5060 Ti. The result drops into `output/` and becomes selectable in
the **Images** page (krea2 LoRAs load straight into the ComfyUI workflow).

## Folder layout

```
training/<base-model>/<your-lora-name>/
    dataset/   <- put 15-40+ images here (.png/.jpg). OPTIONAL: a .txt with the same
                  filename as each image, holding its caption. No captions? I auto-caption.
    output/    <- the trained <your-lora-name>.safetensors lands here.
```

A LoRA only works on the model family it was trained on, so the **base model** is the
top folder:

| Folder   | Base model                                  | Training cost on 16 GB |
|----------|---------------------------------------------|------------------------|
| `krea2/` | the flat-cartoon model used in your videos (Qwen-Image class) | Heaviest — fp8 + block-swap, a few hours |
| `flux/`  | FLUX.1                                       | Heavy — needs FLUX weights (~24 GB) |
| `sdxl/`  | SDXL                                         | Moderate — base ~7 GB |
| `sd15/`  | Stable Diffusion 1.5 (you already have this) | Easiest/fastest — base ~2 GB |

The **type** of LoRA is just how you name the folder, e.g.:

```
krea2/cartoon-character-bob/     (a recurring character)
krea2/woodcut-style/             (a visual style)
sdxl/my-logo-concept/            (an object/concept)
```

## To train one, tell me:

1. **Which folder** (base model + lora name) — i.e. where you dropped the images.
2. A **trigger word** (e.g. `bobcartoon`) to invoke the LoRA in prompts.
3. **Type**: style / character / concept (affects captioning + settings).
4. **Captions**: provide `.txt` files next to the images, or just say *"auto-caption"*.

Then I'll validate/resize the images, write the trainer config, run training, and put
`<your-lora-name>.safetensors` in `output/`.

## Heads-up about your machine

- **Disk is ~99% full.** Trainers + base weights need several GB free. The redundant
  model **copies** in `C:\AAAFlow\models` (krea2/qwen3vl/vae/lora ≈ 18 GB) are no longer
  used (ComfyUI uses its own originals) and can be deleted to make room — just say the
  word.
- **VRAM is 16 GB.** Good dataset size for a style LoRA is ~20-40 images; for a character,
  ~15-30 with varied poses/angles.
