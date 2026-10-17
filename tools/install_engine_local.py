"""安装引擎：解压整合包 → 整理目录 → 生成启动配置。

引擎必须放在纯英文路径下（GPT-SoVITS 对中文路径敏感），默认装到
F:/MamboVoiceEngine/GPT-SoVITS；也可以由安装向导让用户自选目录。

用法：
    python tools/install_engine_local.py                # 自动找 engine_temp 里的包
    python tools/install_engine_local.py --pkg xxx.7z
    python tools/install_engine_local.py --dest D:/MamboVoiceEngine/GPT-SoVITS
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 解压后的大致体积，只用于进度条估算
EXPECTED_INSTALL_GB = 18.0

SEVEN_ZIP_CANDIDATES = [
    "C:/Program Files/7-Zip/7z.exe",
    "C:/Program Files (x86)/7-Zip/7z.exe",
]

ProgressFn = Callable[[dict], None]


class InstallError(RuntimeError):
    """安装失败，消息可直接展示给用户。"""


class CancelledError(RuntimeError):
    """用户主动取消。"""


def default_dest() -> str:
    """挑一个空间足够的盘装引擎（优先 F，其次 D/E/C），避免写死盘符。"""
    for drive in ("F:", "D:", "E:", "C:"):
        root = drive + os.sep
        try:
            if os.path.exists(root) and shutil.disk_usage(root).free > 45 * 1024 ** 3:
                return os.path.join(root, "MamboVoiceEngine", "GPT-SoVITS")
        except OSError:
            continue
    # 兜底：软件所在盘
    home_drive = os.path.splitdrive(ROOT)[0] or "C:"
    return os.path.join(home_drive + os.sep, "MamboVoiceEngine", "GPT-SoVITS")


def install_dir_for_download(dest: str) -> str:
    """整合包要下到哪个目录：跟随安装盘，避免撑爆 C 盘。

    如果算出来的位置正好落在安装目录内部（例如 dest 就是
    D:/MamboVoiceEngine），就换一个不会和安装目录重叠的位置，
    否则安装前「目录必须为空」的检查会被自己下载的文件绊倒。
    """
    dest_abs = os.path.abspath(dest)
    drive = os.path.splitdrive(dest_abs)[0]
    if not drive:
        return os.path.join(ROOT, "engine_temp")

    candidate = os.path.join(drive + os.sep, "MamboVoiceEngine", "_download")
    d = os.path.normcase(dest_abs).rstrip(os.sep)
    c = os.path.normcase(candidate)
    if c == d or c.startswith(d + os.sep):
        candidate = os.path.join(drive + os.sep, "_mambo_download")
    return candidate


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _report(on_progress: ProgressFn | None, phase: str, text: str, **extra) -> None:
    if on_progress is None:
        return
    event = {"phase": phase, "text": text}
    event.update(extra)
    try:
        on_progress(event)
    except Exception:
        pass


def find_7z() -> str:
    """定位 7z 可执行文件：系统 7-Zip → PATH → tools/7zr.exe。"""
    for p in SEVEN_ZIP_CANDIDATES:
        if os.path.isfile(p):
            return p
    for exe in ("7z", "7za", "7zz"):
        hit = shutil.which(exe)
        if hit:
            return hit
    local = os.path.join(ROOT, "tools", "7zr.exe")
    if os.path.isfile(local):
        return local
    raise InstallError(
        "找不到 7-Zip 解压工具，没法解开 8.2GB 的整合包。\n"
        "任选一种方式解决：\n"
        "  1. 安装 7-Zip：https://www.7-zip.org/download.html （装完重新运行本向导）\n"
        "  2. 把 7zr.exe 放到软件的 tools 目录下再重试"
    )


def find_package() -> str:
    for pat in ("*.7z", "*.7z.001"):
        hits = glob.glob(os.path.join(ROOT, "engine_temp", pat))
        if hits:
            return max(hits, key=os.path.getsize)
    raise InstallError("engine_temp 里没有整合包，请先运行 tools/download_engine.py")


def looks_like_engine(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "api.py")) and os.path.isdir(
        os.path.join(path, "runtime"))


def locate_engine_root(extract_dir: str) -> str | None:
    """在解压结果里找到真正含 api.py 的目录。"""
    if looks_like_engine(extract_dir):
        return extract_dir
    for entry in os.listdir(extract_dir):
        cand = os.path.join(extract_dir, entry)
        if not os.path.isdir(cand):
            continue
        if looks_like_engine(cand):
            return cand
        for sub in os.listdir(cand):
            deeper = os.path.join(cand, sub)
            if os.path.isdir(deeper) and looks_like_engine(deeper):
                return deeper
    return None


def scan_models(engine_root: str) -> list[str]:
    found = []
    for ext in ("*.pth", "*.ckpt", "*.wav"):
        for p in glob.glob(os.path.join(engine_root, "**", ext), recursive=True):
            try:
                if os.path.getsize(p) > 1024 * 1024:
                    found.append(p)
            except OSError:
                continue
    return found


def update_config(engine_dir: str) -> None:
    cfg_path = os.path.join(ROOT, "config.json")
    data: dict = {}
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data["engine_dir"] = engine_dir
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log(f"  警告：写入 config.json 失败（{e}），请手动把 engine_dir 改成 {engine_dir}")


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def install(pkg: str | None = None,
            dest: str | None = None,
            keep_pkg: bool = False,
            on_progress: ProgressFn | None = None,
            cancel_event: threading.Event | None = None) -> str:
    """解压并安装引擎到 dest，返回最终引擎目录。

    调用方（安装向导）可以传 on_progress 收进度事件、
    传 cancel_event 支持取消。
    """
    def check_cancel() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("安装已取消")

    dest = os.path.abspath(dest or default_dest())

    # ---- 已经装好：直接复用，不重复下载解压 ----
    if looks_like_engine(dest):
        log(f"引擎已存在：{dest}")
        update_config(dest)
        _report(on_progress, "done", f"引擎已存在，直接使用：{dest}", dest=dest)
        return dest

    # ---- 目标目录安全检查：非空目录一律不覆盖 ----
    if os.path.exists(dest) and not os.path.isdir(dest):
        raise InstallError(f"目标路径已经存在，而且不是文件夹：{dest}")
    if os.path.isdir(dest):
        try:
            leftovers = os.listdir(dest)
        except OSError as e:
            raise InstallError(f"读取目标目录失败：{dest}（{e}）") from e
        if leftovers:
            raise InstallError(
                f"目标目录不是空目录：{dest}\n"
                "为避免覆盖你已有的文件，请换一个空目录（或新建一个子目录）安装。"
            )

    pkg_path = os.path.abspath(pkg) if pkg else find_package()
    if not os.path.isfile(pkg_path):
        raise InstallError(f"整合包不存在：{pkg_path}")

    size_gb = os.path.getsize(pkg_path) / 1024 ** 3
    log(f"整合包：{pkg_path}（{size_gb:.2f} GB）")

    try:
        free = shutil.disk_usage(os.path.splitdrive(dest)[0] + os.sep).free
        if free < size_gb * 3 * 1024 ** 3:
            log(f"警告：磁盘剩余 {free / 1024 ** 3:.1f} GB，建议至少 {size_gb * 3:.1f} GB")
    except OSError:
        pass

    seven = find_7z()
    check_cancel()

    parent = os.path.dirname(dest)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as e:
        raise InstallError(f"没法创建安装目录的上级目录：{parent}（{e}）") from e

    extract_dir = parent + "_extract"
    if os.path.isdir(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
    try:
        os.makedirs(extract_dir, exist_ok=True)
    except OSError as e:
        raise InstallError(f"没法创建临时解压目录：{extract_dir}（{e}）") from e

    log(f"开始解压到 {extract_dir} …（约 {EXPECTED_INSTALL_GB:.0f} GB，可能需要几分钟）")
    _report(on_progress, "extract", "正在解压整合包…", pct=0.0)
    t0 = time.time()
    proc = subprocess.Popen([seven, "x", pkg_path, f"-o{extract_dir}", "-y"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            try:
                proc.kill()
            except Exception:
                pass
            raise CancelledError("安装已取消")
        time.sleep(1.0)
        extracted = _dir_size(extract_dir)
        gb = extracted / 1024 ** 3
        pct = min(gb / EXPECTED_INSTALL_GB * 100.0, 99.0)
        log(f"  … {int(time.time() - t0)}s 已解压 {gb:5.1f} GB")
        _report(on_progress, "extract", f"正在解压… 已解压 {gb:.1f} GB", pct=pct)

    if proc.returncode != 0:
        raise InstallError(f"解压失败（7-Zip 退出码 {proc.returncode}）。可以把整合包删掉重下一次。")

    log("解压完成，正在定位引擎目录…")
    _report(on_progress, "locate", "正在定位引擎目录…", pct=99.0)
    root = locate_engine_root(extract_dir)
    if root is None:
        raise InstallError(
            f"解压结果里没找到 api.py + runtime，请检查 {extract_dir}\n"
            "（可能整合包不完整，删掉后重新下载）"
        )

    if os.path.normcase(os.path.abspath(root)) != os.path.normcase(dest):
        log(f"移动到目标目录：{dest}")
        _report(on_progress, "move", "正在移动到安装目录…", pct=99.0)
        if os.path.isdir(dest):
            # 上面已确认是空目录，删掉不影响用户数据
            shutil.rmtree(dest, ignore_errors=True)
        try:
            shutil.move(root, dest)
        except OSError as e:
            raise InstallError(f"移动引擎到 {dest} 失败：{e}") from e

    shutil.rmtree(extract_dir, ignore_errors=True)
    if not keep_pkg:
        log("清理整合包…")
        _report(on_progress, "cleanup", "清理整合包…", pct=99.0)
        try:
            os.remove(pkg_path)
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
    log("=" * 56)
    _report(on_progress, "done", f"引擎安装完成：{dest}", dest=dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", help="整合包路径，默认自动查找")
    ap.add_argument("--dest", default=None, help="引擎安装目录（默认自动挑选空间足够的盘）")
    ap.add_argument("--keep-pkg", action="store_true", help="解压后保留整合包")
    args = ap.parse_args(argv)

    try:
        install(pkg=args.pkg, dest=args.dest, keep_pkg=args.keep_pkg)
    except CancelledError:
        log("已取消。")
        return 130
    except InstallError as e:
        log(f"[错误] {e}")
        return 1

    log("下一步：双击启动.bat 打开曼波配音工坊。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
