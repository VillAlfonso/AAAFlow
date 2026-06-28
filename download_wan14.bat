@echo off
title Wan 2.2 14B (i2v) download
setlocal
set "CK=C:\AAAFlow\ComfyUI_windows_portable\ComfyUI\models"
echo ============================================================
echo  Downloading Wan 2.2 14B image-to-video (fp8) into ComfyUI (~36 GB)
echo    high-noise expert  ~13.6 GB   -> diffusion_models
echo    low-noise  expert  ~13.6 GB   -> diffusion_models
echo    umt5 text encoder  ~6.4 GB    -> text_encoders
echo    wan 2.1 VAE        ~0.24 GB   -> vae
echo    lightx2v 4-step LoRAs x2      -> loras
echo  Resumable (-C -). Safe to close and re-run.
echo ============================================================
echo.
echo [1/6] high-noise expert...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\diffusion_models\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors" "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
echo [2/6] low-noise expert...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\diffusion_models\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors" "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
echo [3/6] umt5 text encoder...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\text_encoders\umt5_xxl_fp8_e4m3fn_scaled.safetensors" "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
echo [4/6] wan 2.1 VAE...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\vae\wan_2.1_vae.safetensors" "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"
echo [5/6] lightx2v 4-step LoRA (high noise)...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\loras\wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors" "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
echo [6/6] lightx2v 4-step LoRA (low noise)...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\loras\wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors" "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"
echo.
echo ==================  WAN 2.2 14B DOWNLOAD COMPLETE  ==================
pause
