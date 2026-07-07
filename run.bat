@echo off
REM Launch AAAFlow Studio + ComfyUI (double-click friendly)
cd /d "%~dp0"
set "HF_HOME=%~dp0models"
echo.
echo   AAAFlow Studio  -^>  http://127.0.0.1:8000
echo   ComfyUI         -^>  http://127.0.0.1:8188
echo   (first voiceover / image downloads its model - be patient)
echo.
REM Start ComfyUI too (user rule 2026-07-05) unless it's already listening.
netstat -ano | findstr ":8188" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
  start "ComfyUI" /min cmd /c "cd /d "%~dp0ComfyUI_windows_portable" && .\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build"
)
start "" http://127.0.0.1:8000
REM Give ComfyUI a few seconds to bind before opening its tab.
start "" /min cmd /c "timeout /t 9 /nobreak >nul & start "" http://127.0.0.1:8188"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
