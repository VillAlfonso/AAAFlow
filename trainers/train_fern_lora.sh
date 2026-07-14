#!/usr/bin/env bash
# Fern style LoRA: Wan2.2 t2v LOW-noise expert, 16 GB card recipe.
# Chain: cache latents -> cache text-encoder outputs -> train.
# Run from C:/AAAFlow with the musubi venv. Logs stream to stdout.
set -eo pipefail
cd "$(dirname "$0")/musubi-tuner"
PY=./.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8   # musubi help/log strings crash cp1252
DS="C:/AAAFlow/data/lora_datasets/fern/dataset.toml"
VAE="C:/AAAFlow/ComfyUI_windows_portable/ComfyUI/models/vae/wan_2.1_vae.safetensors"
T5="C:/AAAFlow/trainers/weights/wan/models_t5_umt5-xxl-enc-bf16.pth"
DIT="C:/AAAFlow/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.2_t2v_low_noise_14B_fp16.safetensors"
OUT="C:/AAAFlow/data/lora_datasets/fern/out"

echo "=== [1/3] cache latents ==="
$PY src/musubi_tuner/wan_cache_latents.py --dataset_config "$DS" --vae "$VAE"

echo "=== [2/3] cache text encoder outputs ==="
$PY src/musubi_tuner/wan_cache_text_encoder_outputs.py --dataset_config "$DS" \
    --t5 "$T5" --batch_size 4

echo "=== [3/3] train (low-noise expert, fp8 base, block swap) ==="
$PY -m accelerate.commands.launch --num_cpu_threads_per_process 1 \
    --mixed_precision fp16 \
    src/musubi_tuner/wan_train_network.py \
    --task t2v-A14B \
    --dit "$DIT" \
    --vae "$VAE" \
    --t5 "$T5" \
    --dataset_config "$DS" \
    --sdpa --fp8_base --blocks_to_swap 24 \
    --network_module networks.lora_wan --network_dim 16 --network_alpha 16 \
    --learning_rate 3e-4 --optimizer_type adamw8bit \
    --gradient_checkpointing --mixed_precision fp16 \
    --max_train_epochs 8 --save_every_n_epochs 2 \
    --timestep_sampling shift --discrete_flow_shift 3.0 \
    --max_timestep 875 --preserve_distribution_shape \
    --seed 42 --output_dir "$OUT" --output_name fern_style_low \
    --log_config
echo "=== training done: $OUT/fern_style_low.safetensors ==="
