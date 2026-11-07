@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call setup.bat
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm EchoStep.spec
if errorlevel 1 exit /b 1
echo.
echo 构建完成：dist\EchoStep\EchoStep.exe
pause
