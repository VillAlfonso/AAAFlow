@echo off
title LTX-2.3 download (fp8 checkpoint + distilled LoRA)
setlocal
set "CK=C:\AAAFlow\ComfyUI_windows_portable\ComfyUI\models"
echo ============================================================
echo  Downloading the LTX-2.3 weights the Animate page needs.
echo  These match ComfyUI's "Image to Video (LTX-2.3)" blueprint.
echo    Checkpoint : ltx-2.3-22b-dev-fp8.safetensors        (~22 GB)  -> checkpoints
echo    Distilled  : ltx-2.3-22b-distilled-lora-384.safetensors      -> loras
echo    Encoder    : gemma_3_12B_it_fp4_mixed.safetensors            -> text_encoders
echo  Resumable (-C -) - safe to close and re-run this file.
echo  NOTE: the older ltx-2-19b-dev-fp4.safetensors in diffusion_models\
echo        is NOT used by these nodes; you can delete it to reclaim ~20 GB.
echo ============================================================
echo.
echo [1/3] Main checkpoint (fp8, model + VAE)...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\checkpoints\ltx-2.3-22b-dev-fp8.safetensors" "https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/main/ltx-2.3-22b-dev-fp8.safetensors"
echo.
echo [2/3] Distilled LoRA (enables few-step sampling)...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\loras\ltx-2.3-22b-distilled-lora-384.safetensors" "https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384.safetensors"
echo.
echo [3/3] Gemma-3 text encoder (skips instantly if already present)...
curl.exe -L -C - --retry 8 --retry-delay 5 -o "%CK%\text_encoders\gemma_3_12B_it_fp4_mixed.safetensors" "https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors"
echo.
echo ==================  LTX-2.3 DOWNLOAD COMPLETE  ==================
echo Reload the Animate page in AAAFlow - it should now say "ready".
pause
