@echo off
cd /d "%~dp0"
title Mambo Voice Studio - Engine Setup

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.10+ is required, but "python" was not found.
  echo Download: https://www.python.org/downloads/
  echo Remember to tick "Add python.exe to PATH" during installation.
  echo.
  pause
  exit /b 1
)

python -c "import requests" >nul 2>nul
if errorlevel 1 (
  echo Installing base dependencies...
  python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests numpy
)

python tools\install_wizard.py
set "RC=%errorlevel%"

if "%RC%"=="2" (
  echo.
  echo tkinter is not available - switching to command line setup.
  echo.
  python tools\download_engine.py
  if errorlevel 1 (
    echo [ERROR] Download failed.
    pause
    exit /b 1
  )
  python tools\install_engine_local.py
  if errorlevel 1 (
    echo [ERROR] Install failed.
    pause
    exit /b 1
  )
) else (
  if not "%RC%"=="0" (
    echo.
    echo [ERROR] Setup exited with code %RC%. See logs\install.log for details.
    pause
  )
)

exit /b %RC%
