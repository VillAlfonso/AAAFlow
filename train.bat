@echo off
REM Train a krea2 LoRA in your own terminal (no Claude needed).
REM Usage:   train.bat <dataset-folder-name> <trigger-word>
REM Example: train.bat Crayon-Capital crayoncapital
REM Put images in:  training\krea2\<dataset-folder-name>\dataset\
if "%~1"=="" (
  echo Usage: train.bat ^<dataset-folder-name^> ^<trigger-word^>
  echo Example: train.bat Crayon-Capital crayoncapital
  echo Datasets live under training\krea2\^<name^>\dataset\
  pause & exit /b 1
)
set "TRIG=%~2"
if "%TRIG%"=="" set "TRIG=%~1"
C:\AAAFlow\.venv\Scripts\python.exe C:\AAAFlow\trainers\train_krea2_lora.py --name "%~1" --trigger "%TRIG%" --epochs 6 --blocks-to-swap 24 --autocaption
echo.
echo ==== done (window stays open) ====
pause
