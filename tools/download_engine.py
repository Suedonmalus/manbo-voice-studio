"""引擎整合包下载器：多源测速 + Range 断点续传 + 自动换源。

用法：
    python tools/download_engine.py                # 自动选 50 系包
    python tools/download_engine.py --general      # 非 50 系包
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time

import requests

F_NVIDIA50 = "GPT-SoVITS-v2pro-20250604-nvidia50.7z"
F_GENERAL = "GPT-SoVITS-v2pro-20250604.7z"

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


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


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


def pick_source(fname: str) -> str:
    urls = [u.replace("{file}", fname) for u in SOURCES]
    scored = []
    for u in urls:
        sp = probe(u)
        host = u.split("/")[2]
        log(f"测速 {host:<24} {sp:5.2f} MB/s")
        if sp > 0:
            scored.append((sp, u))
    if not scored:
        raise SystemExit("所有下载源均不可用")
    scored.sort(reverse=True)
    return scored[0][1]


def download(fname: str) -> str:
    os.makedirs(TEMP_DIR, exist_ok=True)
    dest = os.path.join(TEMP_DIR, fname)
    total = SIZE[fname]
    if os.path.exists(dest) and os.path.getsize(dest) == total:
        log(f"已存在完整文件：{dest}")
        return dest

    url = pick_source(fname)
    log(f"选用源：{url.split('/')[2]}")
    deadline = time.time() + 6 * 3600
    attempt = 0
    while time.time() < deadline:
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
                    time.sleep(2)
                    url = pick_source(fname)
                    continue
                mode = "ab" if have and r.status_code == 206 else "wb"
                t_last, n_last = time.time(), have
                with open(dest, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        if not chunk:
                            continue
                        f.write(chunk)
                        have += len(chunk)
                        now = time.time()
                        if now - t_last >= 5:
                            sp = (have - n_last) / (now - t_last) / 1048576
                            pct = have / total * 100
                            eta = (total - have) / max(sp, 1e-6) / 60
                            log(f"  {pct:5.1f}%  {have / 1048576:7.1f} MB  {sp:5.2f} MB/s  剩 {eta:4.1f} min")
                            t_last, n_last = now, have
                            if have >= total:
                                break
        except Exception as e:
            log(f"下载中断（{type(e).__name__}: {str(e)[:80]}），3 秒后续传")
            time.sleep(3)
            continue
    if os.path.getsize(dest) != total:
        raise SystemExit(f"下载未完成：{os.path.getsize(dest)} / {total}")
    log(f"下载完成：{dest}")
    return dest


def sha256sum(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--general", action="store_true", help="下载非 50 系整合包")
    ap.add_argument("--verify", action="store_true", help="下载后校验 sha256")
    args = ap.parse_args()
    fname = F_GENERAL if args.general else F_NVIDIA50
    path = download(fname)
    if args.verify:
        log(f"sha256 = {sha256sum(path)}")


if __name__ == "__main__":
    sys.exit(main())
