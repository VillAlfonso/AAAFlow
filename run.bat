@echo off
REM Launch AAAFlow Studio (double-click friendly)
cd /d "%~dp0"
set "HF_HOME=%~dp0models"
echo.
echo   AAAFlow Studio  ->  http://127.0.0.1:8000
echo   (first voiceover / image downloads its model - be patient)
echo.
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
