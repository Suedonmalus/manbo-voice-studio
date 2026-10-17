@echo off
cd /d "%~dp0"
title Mambo Voice Studio - Uninstall

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.10+ is required, but "python" was not found.
  echo Download: https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

python tools\uninstall.py
if errorlevel 1 (
  echo.
  echo [NOTE] Uninstall cancelled or finished with warnings.
  pause
)

exit /b 0
