"""非交互全自动安装器 —— 给 AI Agent 调用。

Agent 只需要知道一个参数：装到哪个目录。

    python tools/agent_install.py --dest "D:/MamboVoiceEngine/GPT-SoVITS"

它会按顺序自己搞定：

    1. 检查 Python 版本（不够就明确报错，不瞎猜）
    2. 准备解压工具：系统装了 7-Zip 就用它，没有就自动下 7zr.exe 到 tools/
    3. 下载并安装 GPT-SoVITS v2Pro 引擎（约 8.2GB，支持断点续传）
    4. 下载曼波音色模型（约 223MB 的压缩包，只取出 3 个文件放进 models/）
    5. 校验安装结果并输出 JSON

约定：
    - 过程日志走 stderr，最终结果 JSON 走 stdout（方便 Agent 解析）
    - 退出码 0 = 成功，1 = 安装失败，2 = Python 版本太低
    - 可重复执行：已经装好的部分会跳过

配套文档见仓库根目录的 AGENT_INSTALL.md。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def say(msg: str) -> None:
    print(f"[agent-install] {msg}", file=sys.stderr, flush=True)


def _ensure_requests() -> None:
    """保证 requests 可用（干净环境里可能还没装）。"""
    try:
        import requests  # noqa: F401
        return
    except ImportError:
        pass
    say("缺少 requests，正在安装基础依赖…")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-i", MIRROR, "requests", "numpy"]
    )
    import requests  # noqa: F401


_ensure_requests()

from tools.download_engine import (  # noqa: E402
    F_GENERAL,
    F_NVIDIA50,
    SIZE,
    DownloadError,
    detect_gpu,
    download,
    pick_package,
)
from tools.install_engine_local import (  # noqa: E402
    InstallError,
    default_dest,
    find_7z,
    install,
    install_dir_for_download,
    looks_like_engine,
    update_config,
)

# ---- 音色模型来源（MIT，见 models/README.md）----
MODEL_ZIP_URL = (
    "https://github.com/Tsukimisaka/MamboTTS/releases/download/v1.2.1/"
    "MamboTTS-v1.2.1-full.zip"
)
MODEL_ZIP_NAME = "MamboTTS-v1.2.1-full.zip"
MODEL_MIN_SIZE = {
    "manbo_e8_s168.pth": 60 * 1024 * 1024,
    "manbo-e10.ckpt": 120 * 1024 * 1024,
    "refer.wav": 64 * 1024,
}

# ---- 免安装的 7zr.exe（602112 字节）----
SEVEN_ZR_URLS = (
    "https://raw.githubusercontent.com/Tsukimisaka/MamboTTS/main/7zr.exe",
    "https://github.com/Tsukimisaka/MamboTTS/raw/main/7zr.exe",
)
SEVEN_ZR_SIZE = 602112

# ---- 安装目录要求 ----
MIN_FREE_GB = 32.0


def check_dest(dest: str) -> tuple[bool, str]:
    """安装目录是否可用（纯英文、非盘根、非系统目录、空间足够、空目录）。"""
    path = os.path.abspath(dest)
    if not path.isascii():
        return False, "安装路径必须全是英文/数字，不能含中文（GPT-SoVITS 的限制）"
    drive, tail = os.path.splitdrive(path)
    if not drive:
        return False, "需要带盘符的绝对路径，例如 D:/MamboVoiceEngine/GPT-SoVITS"
    if tail in ("", os.sep, "/"):
        return False, "不能直接装到盘符根目录，请指定一个子目录"
    low = path.lower()
    for bad in ("c:" + os.sep + "windows", "c:" + os.sep + "program files",
                "c:" + os.sep + "programdata"):
        if low.startswith(bad):
            return False, "不要装到系统目录"
    root_dir = drive + os.sep
    if not os.path.exists(root_dir):
        return False, f"盘符 {drive} 不存在"
    if os.path.isdir(path) and not looks_like_engine(path):
        try:
            if os.listdir(path):
                return False, "目标目录不是空的；请换一个空目录，避免覆盖已有文件"
        except OSError as e:
            return False, f"读取目标目录失败：{e}"
    try:
        free_gb = shutil.disk_usage(root_dir).free / 1024 ** 3
    except OSError as e:
        return False, f"读取磁盘空间失败：{e}"
    if free_gb < MIN_FREE_GB:
        return False, f"{drive} 只剩 {free_gb:.1f} GB，至少需要 {MIN_FREE_GB:.0f} GB"
    return True, ""


def ensure_seven_zip(dry_run: bool = False) -> tuple[str, str]:
    """返回 (7z 可执行文件路径, 来源说明)。没有就下载 7zr.exe。"""
    try:
        return find_7z(), "system"
    except InstallError:
        pass

    target = os.path.join(ROOT, "tools", "7zr.exe")
    if dry_run:
        return target, "would-download"

    say("没有找到 7-Zip，正在下载免安装的 7zr.exe（约 590KB）…")
    import requests

    last_err = ""
    for url in SEVEN_ZR_URLS:
        try:
            r = requests.get(url, timeout=(10, 60))
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code} @ {url.split('/')[2]}"
                continue
            data = r.content
            if len(data) != SEVEN_ZR_SIZE:
                last_err = f"文件大小不符（{len(data)} != {SEVEN_ZR_SIZE}）"
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)
            say(f"7zr.exe 已保存：{target}")
            return target, "downloaded"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue

    raise InstallError(
        f"自动下载 7zr.exe 失败（{last_err}）。\n"
        "请手动安装 7-Zip（https://www.7-zip.org/download.html）后重新运行本脚本。"
    )


def ensure_engine(dest: str, dry_run: bool = False) -> dict:
    """下载并安装引擎，返回结果描述。"""
    if looks_like_engine(dest):
        say(f"引擎已存在，跳过安装：{dest}")
        update_config(dest)
        return {"ok": True, "path": dest, "reused": True}

    pkg_name = pick_package(interactive=False)
    pkg_gb = SIZE.get(pkg_name, 0) / 1024 ** 3
    kind, gpu = detect_gpu()
    say(f"显卡：{gpu} → 整合包 {pkg_name}（约 {pkg_gb:.1f} GB）")

    if dry_run:
        return {"ok": True, "path": dest, "reused": False,
                "package": pkg_name, "would_download_gb": round(pkg_gb, 1)}

    dl_dir = install_dir_for_download(dest)
    say(f"下载目录：{dl_dir}")
    pkg_path = download(pkg_name, dest_dir=dl_dir)
    say("下载完成，开始解压安装（这一步最慢，约 5-15 分钟）…")
    install(pkg=pkg_path, dest=dest)
    return {"ok": True, "path": dest, "reused": False, "package": pkg_name}


def _download_file(url: str, target: str) -> None:
    """带断点续传的下载：中断后重跑会从 .part 继续。"""
    import requests

    tmp = target + ".part"
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with requests.get(url, stream=True, headers=headers, timeout=(10, 60)) as r:
        if r.status_code == 416:  # 本地 .part 反而比远端大，重来
            os.remove(tmp)
            raise InstallError("模型包缓存异常，已清理，请重新运行本脚本")
        if r.status_code not in (200, 206):
            raise InstallError(f"下载模型包失败：HTTP {r.status_code}")
        if have and r.status_code == 200:  # 服务器不支持断点，从头来
            have = 0
        mode = "ab" if have and r.status_code == 206 else "wb"
        total = have + int(r.headers.get("Content-Length") or 0)
        done, last_log = have, time.time()
        with open(tmp, mode) as f:
            for chunk in r.iter_content(1 << 20):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if time.time() - last_log >= 5:
                    last_log = time.time()
                    pct = f"{done / total * 100:5.1f}%" if total else ""
                    say(f"  模型包 {done / 1048576:.0f} MB {pct}")
    os.replace(tmp, target)


def ensure_models(dest: str, dry_run: bool = False, keep_zip: bool = False,
                  models_dir: str | None = None) -> dict:
    """把 3 个音色模型文件准备好（缺什么补什么）。"""
    models_dir = models_dir or os.path.join(ROOT, "models")
    missing = [
        name for name, min_size in MODEL_MIN_SIZE.items()
        if not (os.path.isfile(os.path.join(models_dir, name))
                and os.path.getsize(os.path.join(models_dir, name)) >= min_size)
    ]
    if not missing:
        say("音色模型已齐全，跳过下载")
        return {"ok": True, "downloaded": False, "files": sorted(MODEL_MIN_SIZE)}

    say(f"缺少音色模型：{', '.join(missing)}")
    if dry_run:
        return {"ok": True, "downloaded": False, "missing": missing,
                "would_download": MODEL_ZIP_NAME}

    work_dir = install_dir_for_download(dest)
    os.makedirs(work_dir, exist_ok=True)
    zip_path = os.path.join(work_dir, MODEL_ZIP_NAME)

    if not (os.path.isfile(zip_path) and zipfile.is_zipfile(zip_path)):
        say(f"下载音色模型包（约 213 MB）：{MODEL_ZIP_NAME}")
        _download_file(MODEL_ZIP_URL, zip_path)
    else:
        say(f"复用已下载的模型包：{zip_path}")

    os.makedirs(models_dir, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            base = os.path.basename(member)
            if base not in MODEL_MIN_SIZE:
                continue
            target = os.path.join(models_dir, base)
            say(f"  提取 {base} …")
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            extracted.append(base)

    if not keep_zip:
        try:
            os.remove(zip_path)
        except OSError:
            pass

    bad = []
    for name, min_size in MODEL_MIN_SIZE.items():
        p = os.path.join(models_dir, name)
        if not (os.path.isfile(p) and os.path.getsize(p) >= min_size):
            bad.append(name)
    if bad:
        raise InstallError(f"模型文件提取后仍不完整：{', '.join(bad)}（压缩包结构可能变了）")

    return {"ok": True, "downloaded": True, "files": sorted(extracted)}


def verify(dest: str) -> dict:
    """静态校验：目录结构 + 模型文件 + config.json。"""
    result = {"engine_ok": looks_like_engine(dest), "files": {}, "config_ok": False}
    models_dir = os.path.join(ROOT, "models")
    all_ok = True
    for name, min_size in MODEL_MIN_SIZE.items():
        p = os.path.join(models_dir, name)
        size = os.path.getsize(p) if os.path.isfile(p) else 0
        ok = size >= min_size
        all_ok = all_ok and ok
        result["files"][name] = {"ok": ok, "size_mb": round(size / 1048576, 1)}
    result["models_ok"] = all_ok

    cfg_path = os.path.join(ROOT, "config.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            result["config_ok"] = (
                os.path.normcase(os.path.abspath(cfg.get("engine_dir", "")))
                == os.path.normcase(os.path.abspath(dest))
            )
        except Exception:
            result["config_ok"] = False

    result["ok"] = bool(result["engine_ok"] and result["models_ok"] and result["config_ok"])
    return result


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="非交互全自动安装器（给 AI Agent 用）")
    ap.add_argument("--dest", default=None,
                    help="引擎安装目录（纯英文绝对路径）。不填则自动挑空间足够的盘")
    ap.add_argument("--skip-models", action="store_true", help="跳过音色模型下载")
    ap.add_argument("--keep-downloads", action="store_true", help="保留下载的模型压缩包")
    ap.add_argument("--dry-run", action="store_true", help="只检查环境和计划，不下载不写文件")
    args = ap.parse_args(argv)

    started = time.time()
    stage = "python"
    result: dict = {"ok": False, "dest": None, "steps": []}

    if sys.version_info < (3, 10):
        result["error"] = (
            f"当前 Python 是 {sys.version.split()[0]}，需要 3.10 或更高版本。\n"
            "请先安装 Python 3.10+（安装时勾选 Add python.exe to PATH）后重新运行。"
        )
        result["stage"] = stage
        _emit(result)
        return 2

    dest = os.path.abspath(args.dest or default_dest())
    result["dest"] = dest
    try:
        stage = "check_dest"
        ok, msg = check_dest(dest)
        if not ok:
            raise InstallError(msg)
        result["steps"].append({"step": "check_dest", "ok": True})

        stage = "seven_zip"
        seven_path, seven_src = ensure_seven_zip(dry_run=args.dry_run)
        result["seven_zip"] = {"path": seven_path, "source": seven_src}
        result["steps"].append({"step": "seven_zip", "ok": True, "source": seven_src})

        stage = "engine"
        result["engine"] = ensure_engine(dest, dry_run=args.dry_run)
        result["steps"].append({"step": "engine", "ok": True})

        stage = "models"
        if args.skip_models:
            result["models"] = {"ok": True, "skipped": True}
            result["steps"].append({"step": "models", "ok": True, "skipped": True})
        else:
            result["models"] = ensure_models(
                dest, dry_run=args.dry_run, keep_zip=args.keep_downloads)
            result["steps"].append({"step": "models", "ok": True})

        stage = "verify"
        if args.dry_run:
            result["verify"] = {"ok": True, "note": "dry-run 未做最终校验"}
        else:
            result["verify"] = verify(dest)
            if not result["verify"]["ok"]:
                raise InstallError(
                    "安装完成但校验没通过："
                    f"{json.dumps(result['verify'], ensure_ascii=False)}")

        result["ok"] = True
        result["steps"].append({"step": "verify", "ok": True})
    except (InstallError, DownloadError) as e:
        result["error"] = str(e)
        result["stage"] = stage
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["stage"] = stage

    result["elapsed_sec"] = round(time.time() - started, 1)
    _emit(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
