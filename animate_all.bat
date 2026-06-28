@echo off
title Animate ALL scenes (LTX-2, resumable)
echo Animating every scene of the project with LTX-2 (image -> video).
echo A ComfyUI window + browser tab will open so you can watch each clip render.
echo ~10-13 min per clip on a 16 GB GPU, so a full project runs for many hours.
echo Resumable: Ctrl-C to stop, re-run this file to continue where it left off.
echo.
echo Usage: animate_all.bat [project_id] [--force]
echo.
C:\AAAFlow\.venv\Scripts\python.exe C:\AAAFlow\trainers\animate_all.py %1 %2
echo.
echo =====================================================================
echo  Batch finished (or stopped). Re-run to resume any remaining scenes.
echo  Then assemble the final MP4 in the web app.
echo =====================================================================
pause
