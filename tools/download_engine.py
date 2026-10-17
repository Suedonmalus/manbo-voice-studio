"""引擎整合包下载器：多源测速 + Range 断点续传 + 自动换源。

既可以被安装向导 ``tools/install_wizard.py`` 直接调用（带进度与取消），
也可以单独在命令行运行：

    python tools/download_engine.py                # 自动识别显卡选包
    python tools/download_engine.py --general      # 强制通用包
    python tools/download_engine.py --nvidia50     # 强制 RTX 50 系包
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from typing import Callable

import requests

F_NVIDIA50 = "GPT-SoVITS-v2pro-20250604-nvidia50.7z"
F_GENERAL = "GPT-SoVITS-v2pro-20250604.7z"

# RTX 50 系是 Blackwell 新架构（sm_120），必须用专门的 CUDA 12.8 整合包；
# 30/40 系等其他 NVIDIA 显卡用通用包；没有 NVIDIA 显卡只能 CPU 推理。
FIFTY_SERIES_RE = re.compile(r"RTX\s*50\d{2}|Blackwell|B[12]00", re.IGNORECASE)

SIZE = {
    F_NVIDIA50: 8835144925,
    F_GENERAL: 8185086602,
}

SOURCES = [
    "https://www.modelscope.cn/models/FlowerCry/gpt-sovits-7z-pacakges/resolve/master/{file}",
    "https://modelscope.cn/api/v1/models/FlowerCry/gpt-sovits-7z-pacakges/repo?Revision=master&FilePath={file}",
    "https://hf-mirror.com/lj1995/GPT-SoVITS-windows-package/resolve/main/{file}?download=true",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(ROOT, "engine_temp")
NO_PROXY = {"http": None, "https": None}

ProgressFn = Callable[[dict], None]


class DownloadError(RuntimeError):
    """下载失败，消息可直接展示给用户。"""


class CancelledError(RuntimeError):
    """用户主动取消。"""


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def _report(on_progress: ProgressFn | None, phase: str, text: str = "", **extra) -> None:
    if on_progress is None:
        return
    event = {"phase": phase, "text": text}
    event.update(extra)
    try:
        on_progress(event)
    except Exception:
        # 回调方（GUI）出问题不能拖垮下载
        pass


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("下载已取消")


def probe(url: str) -> float:
    """Range 采样测速，返回 MB/s（失败返回 0）。"""
    try:
        t0 = time.time()
        got = 0
        r = requests.get(url, headers={"Range": "bytes=0-2097151"}, stream=True,
                         timeout=(8, 20), proxies=NO_PROXY)
        if r.status_code not in (200, 206):
            return 0.0
        for ch in r.iter_content(65536):
            got += len(ch)
            if got >= 2097152:
                break
        dt = max(time.time() - t0, 1e-6)
        return got / dt / 1048576
    except Exception:
        return 0.0


def pick_source(fname: str, on_progress: ProgressFn | None = None,
                cancel_event: threading.Event | None = None) -> str:
    urls = [u.replace("{file}", fname) for u in SOURCES]
    scored = []
    for i, u in enumerate(urls, 1):
        _check_cancel(cancel_event)
        host = u.split("/")[2]
        _report(on_progress, "probe", f"正在测速 {i}/{len(urls)}：{host}")
        sp = probe(u)
        log(f"测速 {host:<24} {sp:5.2f} MB/s")
        _report(on_progress, "probe", f"测速完成：{host} {sp:.2f} MB/s", speed=sp)
        if sp > 0:
            scored.append((sp, u))
    if not scored:
        raise DownloadError("所有下载源都连不上。请检查网络，或手动下载整合包放进 engine_temp\\ 后重试。")
    scored.sort(reverse=True)
    return scored[0][1]


def download(fname: str,
             dest_dir: str | None = None,
             on_progress: ProgressFn | None = None,
             cancel_event: threading.Event | None = None) -> str:
    """下载整合包到 ``dest_dir``，返回本地路径。

    已存在且大小一致的文件会直接复用（断点续传的基础）。
    """
    dest_dir = os.path.abspath(dest_dir) if dest_dir else TEMP_DIR
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, fname)
    total = SIZE.get(fname)
    if total is None:
        raise DownloadError(f"未知的整合包文件名：{fname}")

    if os.path.exists(dest) and os.path.getsize(dest) == total:
        log(f"已存在完整文件：{dest}")
        _report(on_progress, "download", "整合包已存在，跳过下载", pct=100.0,
                have=total, total=total)
        return dest

    url = pick_source(fname, on_progress, cancel_event)
    log(f"选用源：{url.split('/')[2]}")
    _report(on_progress, "download", f"选用下载源：{url.split('/')[2]}", pct=0.0,
            have=0, total=total)

    deadline = time.time() + 6 * 3600
    attempt = 0
    while time.time() < deadline:
        _check_cancel(cancel_event)
        attempt += 1
        have = os.path.getsize(dest) if os.path.exists(dest) else 0
        if have >= total:
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        log(f"第 {attempt} 次请求，从 {have / 1048576:.1f} MB / {total / 1048576:.1f} MB 续传")
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(10, 60),
                              proxies=NO_PROXY) as r:
                if r.status_code not in (200, 206):
                    log(f"HTTP {r.status_code}，换源重试")
                    _report(on_progress, "download", f"源返回 HTTP {r.status_code}，正在换源…",
                            pct=have / total * 100, have=have, total=total)
                    time.sleep(2)
                    url = pick_source(fname, on_progress, cancel_event)
                    continue
                mode = "ab" if have and r.status_code == 206 else "wb"
                t_last, n_last = time.time(), have
                with open(dest, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        _check_cancel(cancel_event)
                        if not chunk:
                            continue
                        f.write(chunk)
                        have += len(chunk)
                        now = time.time()
                        if now - t_last >= 1.0:
                            sp = (have - n_last) / (now - t_last) / 1048576
                            pct = min(have / total * 100, 100.0)
                            eta = (total - have) / max(sp, 1e-6)
                            log(f"  {pct:5.1f}%  {have / 1048576:7.1f} MB  {sp:5.2f} MB/s")
                            _report(on_progress, "download",
                                    f"{have / 1048576:.0f} MB / {total / 1048576:.0f} MB",
                                    pct=pct, speed=sp, eta=eta, have=have, total=total)
                            t_last, n_last = now, have
                            if have >= total:
                                break
        except CancelledError:
            raise
        except Exception as e:
            log(f"下载中断（{type(e).__name__}: {str(e)[:80]}），3 秒后续传")
            _report(on_progress, "download", f"连接中断，正在续传…（{type(e).__name__}）",
                    pct=(os.path.getsize(dest) if os.path.exists(dest) else 0) / total * 100,
                    have=(os.path.getsize(dest) if os.path.exists(dest) else 0), total=total)
            time.sleep(3)
            continue

    final_size = os.path.getsize(dest) if os.path.exists(dest) else 0
    if final_size != total:
        raise DownloadError(
            f"下载没有完成：{final_size / 1048576:.1f} MB / {total / 1048576:.1f} MB。\n"
            "重新运行安装向导即可从断点继续。"
        )
    log(f"下载完成：{dest}")
    _report(on_progress, "download", "整合包下载完成", pct=100.0, have=total, total=total)
    return dest


def sha256sum(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_gpu() -> tuple[str, str]:
    """检测显卡，返回 (整合包类型, 显卡名)。类型：nvidia50 / general / cpu。"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15, creationflags=creationflags,
        )
        names = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
    except Exception:
        names = []

    if not names:
        return "cpu", "未检测到 NVIDIA 显卡"
    name = names[0]
    return ("nvidia50" if FIFTY_SERIES_RE.search(name) else "general"), name


def pick_package(force_general: bool = False,
                 force_50: bool = False,
                 interactive: bool = True) -> str:
    """决定下载哪个整合包。

    interactive=True 时用于命令行：打印说明、CPU 模式下等待 5 秒。
    安装向导传 False，避免阻塞与控制台噪音。
    """
    gpu_type, gpu_name = detect_gpu()
    if interactive:
        print(f"检测到显卡：{gpu_name}")
    if force_general:
        if interactive:
            print("  → 手动指定：通用整合包（30/40 系或 CPU）")
        return F_GENERAL
    if force_50:
        if interactive:
            print("  → 手动指定：RTX 50 系整合包")
        return F_NVIDIA50

    if gpu_type == "nvidia50":
        if interactive:
            print("  → 识别为 RTX 50 系（Blackwell），下载专用整合包")
        return F_NVIDIA50
    if gpu_type == "general":
        if interactive:
            print("  → 识别为其他 NVIDIA 显卡，下载通用整合包")
        return F_GENERAL

    if interactive:
        print("  → 没有 NVIDIA 显卡，只能 CPU 推理：可以跑，但合成速度慢 20-50 倍。")
        print("     下载通用整合包，5 秒后开始（Ctrl+C 取消）…")
        time.sleep(5)
    return F_GENERAL


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--general", action="store_true", help="强制下载通用整合包（30/40 系）")
    ap.add_argument("--nvidia50", action="store_true", help="强制下载 RTX 50 系整合包")
    ap.add_argument("--dir", default=None, help="整合包临时保存目录（默认 engine_temp/）")
    ap.add_argument("--verify", action="store_true", help="下载后校验 sha256")
    args = ap.parse_args()
    fname = pick_package(args.general, args.nvidia50)
    try:
        path = download(fname, dest_dir=args.dir)
    except CancelledError:
        log("已取消。")
        return 130
    except DownloadError as e:
        log(f"[错误] {e}")
        return 1
    if args.verify:
        log(f"sha256 = {sha256sum(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
