@echo off
cd /d "%~dp0"
title 安装 GPT-SoVITS 引擎

echo ============================================================
echo            曼波配音工坊 - 引擎安装向导
echo ============================================================
echo.
echo  引擎：GPT-SoVITS v2Pro（NVIDIA 显卡本地推理）
echo  大小：整合包约 8.2GB，解压后约 18GB
echo  位置：F:\MamboVoiceEngine\GPT-SoVITS（纯英文路径，避免加载异常）
echo.
echo  已安装过引擎的话，本脚本会检测到并直接跳过。
echo.
pause

python -c "import requests" >nul 2>nul
if errorlevel 1 (
  echo 正在安装基础依赖...
  python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests numpy
)

echo.
echo [1/2] 下载引擎整合包（支持断点续传，中断后重跑本脚本即可续传）
python tools\download_engine.py
if errorlevel 1 goto fail

echo.
echo [2/2] 解压并安装引擎
python tools\install_engine_local.py
if errorlevel 1 goto fail

echo.
echo ============================================================
echo  安装完成！接下来双击「启动.bat」打开曼波配音工坊。
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [错误] 安装过程出错，请把上面的日志发给开发者。
echo 可手动下载整合包放进 engine_temp\ 后重跑本脚本（会跳过下载直接解压）。
pause
exit /b 1
