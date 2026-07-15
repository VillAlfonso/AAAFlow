#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/musubi-tuner"
PY=./.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8
DS="C:/AAAFlow/data/lora_datasets/fern_pure/dataset.toml"
VAE="C:/AAAFlow/ComfyUI_windows_portable/ComfyUI/models/vae/wan_2.1_vae.safetensors"
T5="C:/AAAFlow/trainers/weights/wan/models_t5_umt5-xxl-enc-bf16.pth"
DIT="C:/AAAFlow/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.2_t2v_low_noise_14B_fp16.safetensors"
OUT="C:/AAAFlow/data/lora_datasets/fern_pure/out"
$PY -m accelerate.commands.launch --num_cpu_threads_per_process 1 --mixed_precision fp16 \
    src/musubi_tuner/wan_train_network.py --task t2v-A14B \
    --dit "$DIT" --vae "$VAE" --t5 "$T5" --dataset_config "$DS" \
    --network_weights "$OUT/fern_pure-000001.safetensors" \
    --sdpa --fp8_base --blocks_to_swap 24 --max_data_loader_n_workers 0 \
    --network_module networks.lora_wan --network_dim 16 --network_alpha 16 \
    --learning_rate 3e-4 --optimizer_type adamw8bit --gradient_checkpointing \
    --mixed_precision fp16 --max_train_epochs 4 --save_every_n_epochs 1 \
    --timestep_sampling shift --discrete_flow_shift 3.0 --max_timestep 875 \
    --preserve_distribution_shape --seed 42 --output_dir "$OUT" \
    --output_name fern_pure_v2 --log_config
echo "=== resume done: fern_pure_v2.safetensors ==="
