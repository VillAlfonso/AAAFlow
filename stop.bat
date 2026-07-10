@echo off
REM Stop AAAFlow Studio and ComfyUI if they are running.
cd /d "%~dp0"
echo Stopping AAAFlow services...

setlocal enabledelayedexpansion
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R ":8000 "') do (
  echo Stopping process on port 8000: PID %%P
  taskkill /PID %%P /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R ":8188 "') do (
  echo Stopping process on port 8188: PID %%P
  taskkill /PID %%P /F >nul 2>&1
)
echo Done.
endlocal
pause
