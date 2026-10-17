@echo off
cd /d "%~dp0"
title 曼波配音工坊

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没有找到 python，请先安装 Python 3.10 或更高版本。
  echo 下载地址：https://www.python.org/downloads/
  pause
  exit /b 1
)

python -c "import PySide6, requests, numpy" >nul 2>nul
if errorlevel 1 (
  echo 首次运行，正在安装依赖（约 100MB，使用清华镜像）...
  python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)

where pythonw >nul 2>nul
if errorlevel 1 (
  python app.py
  if errorlevel 1 pause
  exit /b 0
)

start "" pythonw app.py
exit /b 0
