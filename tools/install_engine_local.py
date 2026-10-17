"""安装引擎：解压整合包 → 整理目录 → 生成启动配置。

引擎必须放在纯英文路径下（GPT-SoVITS 对中文路径敏感），
因此默认安装到 F:\\MamboVoiceEngine\\GPT-SoVITS。

用法：
    python tools/install_engine_local.py                # 自动找 engine_temp 里的包
    python tools/install_engine_local.py --pkg xxx.7z
    python tools/install_engine_local.py --dest D:\\MamboVoiceEngine\\GPT-SoVITS
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DEST = r"F:\MamboVoiceEngine\GPT-SoVITS"

SEVEN_ZIP_CANDIDATES = [
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_7z() -> str:
    for p in SEVEN_ZIP_CANDIDATES:
        if os.path.isfile(p):
            return p
    local = os.path.join(ROOT, "tools", "7zr.exe")
    if os.path.isfile(local):
        return local
    raise SystemExit("找不到 7z 解压工具：请安装 7-Zip，或把 7zr.exe 放到 tools/ 目录")


def find_package() -> str:
    for pat in ("*.7z", "*.7z.001"):
        hits = glob.glob(os.path.join(ROOT, "engine_temp", pat))
        if hits:
            return max(hits, key=os.path.getsize)
    raise SystemExit("engine_temp/ 里没有整合包，请先运行 tools/download_engine.py")


def looks_like_engine(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "api.py")) and os.path.isdir(
        os.path.join(path, "runtime"))


def locate_engine_root(extract_dir: str) -> str | None:
    """在解压结果里找到真正含 api.py 的目录。"""
    if looks_like_engine(extract_dir):
        return extract_dir
    for entry in os.listdir(extract_dir):
        cand = os.path.join(extract_dir, entry)
        if os.path.isdir(cand) and looks_like_engine(cand):
            return cand
        if os.path.isdir(cand):
            for sub in os.listdir(cand):
                deeper = os.path.join(cand, sub)
                if os.path.isdir(deeper) and looks_like_engine(deeper):
                    return deeper
    return None


def scan_models(engine_root: str) -> list[str]:
    found = []
    for ext in ("*.pth", "*.ckpt", "*.wav"):
        for p in glob.glob(os.path.join(engine_root, "**", ext), recursive=True):
            if os.path.getsize(p) > 1024 * 1024:
                found.append(p)
    return found


def update_config(engine_dir: str) -> None:
    cfg_path = os.path.join(ROOT, "config.json")
    data = {}
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data["engine_dir"] = engine_dir
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", help="整合包路径，默认自动查找")
    ap.add_argument("--dest", default=DEFAULT_DEST, help=f"引擎安装目录，默认 {DEFAULT_DEST}")
    ap.add_argument("--keep-pkg", action="store_true", help="解压后保留整合包")
    args = ap.parse_args()

    dest = os.path.abspath(args.dest)
    if looks_like_engine(dest):
        log(f"引擎已存在：{dest}")
        update_config(dest)
        return 0

    pkg = os.path.abspath(args.pkg) if args.pkg else find_package()
    size_gb = os.path.getsize(pkg) / 1024 ** 3
    log(f"整合包：{pkg}（{size_gb:.2f} GB）")

    free = shutil.disk_usage(os.path.splitdrive(dest)[0] + "\\").free
    if free < size_gb * 3 * 1024 ** 3:
        log(f"警告：磁盘剩余 {free / 1024 ** 3:.1f} GB，建议至少 {size_gb * 3:.1f} GB")

    seven = find_7z()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    extract_dir = os.path.dirname(dest) + "_extract"
    if os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir, exist_ok=True)

    log(f"开始解压到 {extract_dir} …（约 18GB，可能需要几分钟）")
    t0 = time.time()
    proc = subprocess.Popen([seven, "x", pkg, f"-o{extract_dir}", "-y"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    while proc.poll() is None:
        time.sleep(5)
        txt = ""
        try:
            total = sum(os.path.getsize(os.path.join(r, f))
                        for r, _, fs in os.walk(extract_dir) for f in fs)
            txt = f"已解压 {total / 1024 ** 3:5.1f} GB"
        except OSError:
            pass
        log(f"  … {int(time.time() - t0)}s {txt}")
    if proc.returncode != 0:
        raise SystemExit(f"解压失败（退出码 {proc.returncode}）")

    log("解压完成，正在定位引擎目录…")
    root = locate_engine_root(extract_dir)
    if root is None:
        raise SystemExit(f"解压结果里没找到 api.py + runtime/，请检查 {extract_dir}")

    if os.path.abspath(root) != dest:
        log(f"移动到目标目录：{dest}")
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
        shutil.move(root, dest)

    shutil.rmtree(extract_dir, ignore_errors=True)
    if not args.keep_pkg:
        log("清理整合包…")
        try:
            os.remove(pkg)
        except OSError as e:
            log(f"  提示：删除整合包失败（可手动删除）：{e}")

    log("扫描引擎内的模型文件：")
    models = scan_models(dest)
    for m in models[:20]:
        log(f"  {os.path.getsize(m) / 1024 ** 2:8.1f} MB  {m}")
    if not models:
        log("  （没有找到大模型文件，需另行下载曼波音色模型）")

    update_config(dest)
    log("=" * 56)
    log("引擎安装完成！")
    log(f"引擎目录：{dest}")
    log("下一步：双击「启动.bat」打开曼波配音工坊。")
    log("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
