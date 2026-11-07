@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
  echo [EchoStep] First run: creating the Python environment...
  call setup.bat
  if errorlevel 1 exit /b 1
)

echo [EchoStep] Starting the desktop window...
.venv\Scripts\python.exe desktop.py %*
if errorlevel 1 (
  echo.
  echo [EchoStep] Startup failed. Please read the error above.
  pause
)
