@echo off
title LTX-2 download (fp4)
setlocal
set "CK=C:\AAAFlow\ComfyUI_windows_portable\ComfyUI\models"
echo ============================================================
echo  Downloading LTX-2 (fp4, Blackwell-native) into ComfyUI
echo    DiT      : ltx-2-19b-dev-fp4.safetensors        (~20 GB)
echo    Encoder  : gemma_3_12B_it_fp4_mixed.safetensors (~9.4 GB)
echo    VAE      : ltx2_vae.safetensors                 (~2.4 GB)
echo  Resumable - safe to close and re-run this file.
echo ============================================================
echo.
echo [1/3] DiT (transformer)...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\diffusion_models\ltx-2-19b-dev-fp4.safetensors" "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-dev-fp4.safetensors"
echo.
echo [2/3] Gemma-3 text encoder (fp4)...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\text_encoders\gemma_3_12B_it_fp4_mixed.safetensors" "https://huggingface.co/Comfy-Org/LTX-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors"
echo.
echo [3/3] VAE...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\vae\ltx2_vae.safetensors" "https://huggingface.co/Lightricks/LTX-2/resolve/main/vae/diffusion_pytorch_model.safetensors"
echo.
echo ==================  LTX-2 DOWNLOAD COMPLETE  ==================
echo Files are in %CK%\(diffusion_models^|text_encoders^|vae)
pause
