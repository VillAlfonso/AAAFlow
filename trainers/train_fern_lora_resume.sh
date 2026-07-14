#!/usr/bin/env bash
# Resume the Fern LoRA (v2 captions) from the last epoch checkpoint.
#
# Two fixes over the first run:
#  1. HANG: it froze at exactly 1278 steps = 3.00 epochs — a Windows
#     dataloader-worker respawn deadlock at the epoch boundary (GPU 0% with
#     VRAM held, zero CPU). Fix: --max_data_loader_n_workers 0 (latents are
#     pre-cached, so main-process loading costs nothing) + save every epoch.
#  2. CAPTIONS: v1 captions described content only, so the LoRA had no words
#     to bind the LOOK to. v2 captions lead with the trigger phrase
#     "3d mannequin documentary" + a media-specific style clause, so the text
#     encoder cache is rebuilt here before training.
set -eo pipefail
cd "$(dirname "$0")/musubi-tuner"
PY=./.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8
DS="C:/AAAFlow/data/lora_datasets/fern/dataset.toml"
VAE="C:/AAAFlow/ComfyUI_windows_portable/ComfyUI/models/vae/wan_2.1_vae.safetensors"
T5="C:/AAAFlow/trainers/weights/wan/models_t5_umt5-xxl-enc-bf16.pth"
DIT="C:/AAAFlow/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.2_t2v_low_noise_14B_fp16.safetensors"
OUT="C:/AAAFlow/data/lora_datasets/fern/out"
RESUME="$OUT/fern_style_low-000002.safetensors"

echo "=== [1/2] re-cache text encoder outputs (v2 style captions) ==="
$PY src/musubi_tuner/wan_cache_text_encoder_outputs.py --dataset_config "$DS" \
    --t5 "$T5" --batch_size 4

echo "=== [2/2] resume train from $(basename "$RESUME") ==="
$PY -m accelerate.commands.launch --num_cpu_threads_per_process 1 \
    --mixed_precision fp16 \
    src/musubi_tuner/wan_train_network.py \
    --task t2v-A14B \
    --dit "$DIT" \
    --vae "$VAE" \
    --t5 "$T5" \
    --dataset_config "$DS" \
    --network_weights "$RESUME" \
    --sdpa --fp8_base --blocks_to_swap 24 \
    --max_data_loader_n_workers 0 \
    --network_module networks.lora_wan --network_dim 16 --network_alpha 16 \
    --learning_rate 3e-4 --optimizer_type adamw8bit \
    --gradient_checkpointing --mixed_precision fp16 \
    --max_train_epochs 5 --save_every_n_epochs 1 \
    --timestep_sampling shift --discrete_flow_shift 3.0 \
    --max_timestep 875 --preserve_distribution_shape \
    --seed 42 --output_dir "$OUT" --output_name fern_style_low_v2 \
    --log_config
echo "=== training done: $OUT/fern_style_low_v2.safetensors ==="
