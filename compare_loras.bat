@echo off
title Crayon-Capital LoRA comparison (epochs 1-6)
echo Rendering 6 challenging prompts x each epoch checkpoint (same seeds)...
echo Output: training\krea2\Crayon-Capital\compare\
echo.
C:\AAAFlow\.venv\Scripts\python.exe C:\AAAFlow\trainers\compare_loras.py
echo.
echo =====================================================================
echo  DONE - open: training\krea2\Crayon-Capital\compare\COMPARISON_GRID.png
echo  Per-epoch folders (ep1..ep6) are in the same compare\ folder.
echo =====================================================================
pause
