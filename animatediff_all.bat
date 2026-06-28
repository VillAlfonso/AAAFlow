@echo off
title Animate scenes with AnimateDiff-SDXL (resumable)
echo Animating scenes in 2D cartoon style with AnimateDiff (~70s per clip after load).
echo Clips appear live in the web app - refresh the Animate page as they finish.
echo Resumable: Ctrl-C to stop, re-run to continue. Add --force to redo all.
echo.
echo Usage: animatediff_all.bat [project_id] [count] [--force]
echo.
C:\AAAFlow\.venv\Scripts\python.exe C:\AAAFlow\trainers\animatediff_all.py %1 %2 %3
echo.
pause
