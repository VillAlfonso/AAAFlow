@echo off
title Cartoon-RAG image smoke test (SDXL + IP-Adapter, no ComfyUI)
echo Generating one cartoon image WITHOUT ComfyUI:
echo   SDXL + IP-Adapter style transfer over your reference pack.
echo First run downloads SDXL + IP-Adapter (~9 GB), then it's local + fast.
echo Output: cartoon_rag_test.png in the project root.
echo.
echo Usage: cartoon_test.bat ["a prompt"] [ip_scale 0..1.2]
echo.
C:\AAAFlow\.venv\Scripts\python.exe C:\AAAFlow\trainers\cartoon_test.py %1 %2
echo.
echo =====================================================================
echo  DONE - open cartoon_rag_test.png.  Tweak ip_scale to taste:
echo    higher = stronger cartoon style from the references.
echo =====================================================================
pause
