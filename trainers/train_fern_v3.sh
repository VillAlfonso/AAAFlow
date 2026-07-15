#!/usr/bin/env bash
# Fern LoRA v3 — MANNEQUIN-ONLY dataset, clothed + blank-headed captions.
#
# Why v3 exists: v2 trained on 225 clips of which only ~21 were actual
# mannequin reconstructions (the rest were archival footage, screenshots,
# talking heads — the dataset sampled evenly instead of filtering). So the
# "3d mannequin documentary" concept barely bound, and Wan's own prior for
# "mannequin" (a NUDE store dummy with a sculpted face) won: the first render
# came back as an uncanny naked half-human. v3 trains only on shots the
# techniques pass classed as 3d-render, with one identical style clause on
# every caption: featureless grey mannequins, blank heads, NO faces, CLOTHED.
#
# Same hard-won flags as before: fp16 mixed precision (the fp16 DiT asserts on
# anything else), --sdpa (Windows needs an explicit attention backend), and
# --max_data_loader_n_workers 0 (worker respawn deadlocks at epoch boundaries).
set -eo pipefail
cd "$(dirname "$0")/musubi-tuner"
PY=./.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8
DS="C:/AAAFlow/data/lora_datasets/fern_mannequin/dataset.toml"
VAE="C:/AAAFlow/ComfyUI_windows_portable/ComfyUI/models/vae/wan_2.1_vae.safetensors"
T5="C:/AAAFlow/trainers/weights/wan/models_t5_umt5-xxl-enc-bf16.pth"
DIT="C:/AAAFlow/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.2_t2v_low_noise_14B_fp16.safetensors"
OUT="C:/AAAFlow/data/lora_datasets/fern_mannequin/out"

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
    --dit "$DIT" --vae "$VAE" --t5 "$T5" \
    --dataset_config "$DS" \
    --sdpa --fp8_base --blocks_to_swap 24 \
    --max_data_loader_n_workers 0 \
    --network_module networks.lora_wan --network_dim 16 --network_alpha 16 \
    --learning_rate 3e-4 --optimizer_type adamw8bit \
    --gradient_checkpointing --mixed_precision fp16 \
    --max_train_epochs 3 --save_every_n_epochs 1 \
    --timestep_sampling shift --discrete_flow_shift 3.0 \
    --max_timestep 875 --preserve_distribution_shape \
    --seed 42 --output_dir "$OUT" --output_name fern_mannequin \
    --log_config
echo "=== training done: $OUT/fern_mannequin.safetensors ==="
