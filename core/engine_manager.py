"""引擎进程管理：检查安装状态、拉起 GPT-SoVITS API 服务、等待端口就绪、关闭。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from core.config import resolve_engine_dir
from core.engine_client import TTSClient

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


def engine_python() -> str:
    return os.path.join(resolve_engine_dir(), "runtime", "python.exe")


def api_script() -> str:
    return os.path.join(resolve_engine_dir(), "api.py")


def is_installed() -> bool:
    return os.path.isfile(engine_python()) and os.path.isfile(api_script())


class EngineManager:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.log_path = os.path.join(LOG_DIR, "engine.log")

    # ---------- 状态 ----------
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def is_online(self, api_url: str) -> bool:
        return TTSClient(api_url).is_online()

    # ---------- 启动 / 停止 ----------
    def start(self, *, api_url: str, sovits: str, gpt: str, ref_wav: str,
              ref_text: str, ref_lang: str = "zh") -> tuple[bool, str]:
        if self.is_running():
            return True, "引擎进程已在运行"
        if not is_installed():
            return False, ("引擎尚未安装：请先双击「安装引擎.bat」下载 GPT-SoVITS 整合包"
                           "（约 8.2GB），或把整合包解压到 engine/GPT-SoVITS/。")
        if not os.path.isfile(ref_wav):
            return False, f"缺少参考音频：{ref_wav}"

        os.makedirs(LOG_DIR, exist_ok=True)
        host_port = api_url.replace("http://", "").replace("https://", "")
        host, _, port = host_port.partition(":")

        cmd = [
            engine_python(), "-X", "utf8", "api.py",
            "-a", host or "127.0.0.1",
            "-p", port or "9880",
        ]
        # 音色模型可选：留空则用引擎自带的 v2Pro 预训练做零样本克隆。
        # 注意参考音频路径必须是纯英文（中文路径会让引擎的 argv 解码出错）。
        if sovits and os.path.isfile(sovits):
            cmd += ["-s", sovits]
        if gpt and os.path.isfile(gpt):
            cmd += ["-g", gpt]
        cmd += ["-dr", ref_wav, "-dt", ref_text, "-dl", ref_lang]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        log_file = open(self.log_path, "a", encoding="utf-8", errors="replace")
        log_file.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动引擎 =====\n")
        log_file.write(" ".join(cmd) + "\n")
        log_file.flush()

        try:
            self.proc = subprocess.Popen(
                cmd, cwd=resolve_engine_dir(), stdout=log_file, stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except OSError as e:
            return False, f"启动引擎失败：{e}"
        return True, "引擎进程已启动"

    def wait_online(self, api_url: str, timeout: float = 120.0, cancel_cb=None) -> bool:
        client = TTSClient(api_url)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cancel_cb and cancel_cb():
                return False
            if client.is_online():
                return True
            if self.proc is not None and self.proc.poll() is not None:
                return False
            time.sleep(0.6)
        return False

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass
        finally:
            self.proc = None
