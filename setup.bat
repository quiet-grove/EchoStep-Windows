@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 (
  echo [EchoStep] Python was not found. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [EchoStep] Step 1/3: creating .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [EchoStep] Failed to create the virtual environment.
    pause
    exit /b 1
  )
)

echo [EchoStep] Step 2/3: installing Python dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-setup.txt
if errorlevel 1 (
  echo [EchoStep] Dependency installation failed. Check your network and retry.
  pause
  exit /b 1
)

if not exist "models\piper\en_US-amy-low.int8.onnx" (
  if not exist "models\piper\en_US-amy-low.onnx" (
    echo [EchoStep] Step 3/3: downloading the small local voice model...
    .venv\Scripts\python.exe tools\install_voice.py en_US-amy-low
  )
)
if exist "models\piper\en_US-amy-low.onnx" (
  if not exist "models\piper\en_US-amy-low.int8.onnx" (
    echo [EchoStep] Compressing the voice model to int8...
    .venv\Scripts\python.exe tools\install_voice.py en_US-amy-low
  )
)

if not exist "models\piper\zh_CN-huayan-x_low.int8.onnx" (
  if not exist "models\piper\zh_CN-huayan-x_low.onnx" (
    echo [EchoStep] Downloading the Chinese voice model for Chinese questions...
    .venv\Scripts\python.exe tools\install_voice.py zh_CN-huayan-x_low
  )
)
if exist "models\piper\zh_CN-huayan-x_low.onnx" (
  if not exist "models\piper\zh_CN-huayan-x_low.int8.onnx" (
    echo [EchoStep] Compressing the Chinese voice model to int8...
    .venv\Scripts\python.exe tools\install_voice.py zh_CN-huayan-x_low
  )
)

echo.
echo [EchoStep] Setup complete. Double-click run.bat to start.
pause
