@echo off
title LTX-2 animation smoke test (one scene)
echo Animating the first rendered still through LTX-2 (image -> video).
echo First run also starts ComfyUI and loads the 22B fp8 model (slow once).
echo Output: an *_ltxtest.mp4 next to the still.
echo.
echo Usage: animate_test.bat [optional_image.png] [seconds]
echo.
C:\AAAFlow\.venv\Scripts\python.exe C:\AAAFlow\trainers\animate_test.py %1 %2
echo.
echo =====================================================================
echo  DONE - open the *_ltxtest.mp4 it printed above.
echo =====================================================================
pause
