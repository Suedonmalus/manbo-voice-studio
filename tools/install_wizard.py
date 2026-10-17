"""曼波配音工坊 · 引擎安装向导。

双击「安装引擎.bat」后弹出这个窗口：先做环境检查，再让用户自己决定引擎
装在哪个盘哪个目录（默认推荐空间足够的盘），然后显示下载与解压进度，
最后把 engine_dir 写进 config.json。

用 tkinter 而不是 PySide6：安装引擎的阶段 PySide6 还没装，tkinter 是
Python 自带，能保证向导本身就一定能跑起来。

用法：
    python tools/install_wizard.py
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TK_OK = True
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:  # 没有 tkinter 的 Python（精简版 / 某些商店版）
    TK_OK = False

from tools.download_engine import (  # noqa: E402
    F_GENERAL,
    F_NVIDIA50,
    SIZE,
    CancelledError as DownloadCancelled,
    DownloadError,
    detect_gpu,
    download,
)
from tools.install_engine_local import (  # noqa: E402
    CancelledError as InstallCancelled,
    InstallError,
    default_dest,
    find_7z,
    install,
    install_dir_for_download,
    looks_like_engine,
    update_config,
)

# 8.2GB 整合包 + 解压后约 18GB，再留一点余量
MIN_FREE_GB = 32.0

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 20, "bold")
FONT_SUB = ("Microsoft YaHei UI", 12)


# ---------------------------------------------------------------- 纯逻辑部分

def validate_target(raw: str, min_free_gb: float = MIN_FREE_GB) -> tuple[bool, str]:
    """检查用户填的安装目录能不能用，返回 (是否通过, 不通过的原因)。"""
    if not raw or not raw.strip():
        return False, "请先选择一个安装目录"

    try:
        path = os.path.abspath(raw.strip())
    except Exception:
        return False, "路径写法有问题，请重新选择"

    if not path.isascii():
        return False, ("路径里有中文或全角字符。GPT-SoVITS 对中文路径敏感，"
                       "请改成纯英文路径，例如 D:/MamboVoiceEngine/GPT-SoVITS")

    drive, tail = os.path.splitdrive(path)
    if not drive:
        return False, "请用带盘符的完整路径，例如 D:/MamboVoiceEngine/GPT-SoVITS"
    if tail in ("", os.sep, "/"):
        return False, "不能直接装到盘符根目录，请在下面新建一个子目录"

    low = path.lower()
    for bad in ("c:" + os.sep + "windows",
                "c:" + os.sep + "program files",
                "c:" + os.sep + "programdata"):
        if low.startswith(bad):
            return False, "不要装到系统目录，请换一个普通目录"

    root_dir = drive + os.sep
    if not os.path.exists(root_dir):
        return False, f"盘符 {drive} 不存在"

    if os.path.isdir(path) and not looks_like_engine(path):
        try:
            if os.listdir(path):
                return False, "这个目录里已经有文件了。为避免覆盖，请选一个空目录（或新建子目录）"
        except OSError as e:
            return False, f"读取目录失败：{e}"

    try:
        free_gb = shutil.disk_usage(root_dir).free / 1024 ** 3
    except OSError as e:
        return False, f"读取磁盘剩余空间失败：{e}"
    if free_gb < min_free_gb:
        return False, (f"{drive} 只剩 {free_gb:.1f} GB，至少需要 {min_free_gb:.0f} GB"
                       "（8.2GB 整合包 + 解压后约 18GB）")
    return True, ""


def download_dir_for(dest: str) -> str:
    """兼容旧名字；真正的实现在 install_engine_local，避免两处逻辑漂移。"""
    return install_dir_for_download(dest)


# ---------------------------------------------------------------- 界面部分

class InstallWizard:
    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.root.title("曼波配音工坊 · 引擎安装向导")
        self.root.resizable(False, False)
        self.root.configure(bg="#ffffff")

        self.dest_var = tk.StringVar(value=default_dest())
        self.stage_var = tk.StringVar(value="准备中…")
        self.speed_var = tk.StringVar(value="")
        self.queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.installing = False
        self.final_dest = ""
        self.gpu_kind = "general"
        self.gpu_name = ""
        self.pkg_file = F_GENERAL
        self._last_log = ""
        self._dest_trace_id = None

        self.body = ttk.Frame(root, padding=(26, 20, 26, 18), style="Body.TFrame")
        self.body.pack(fill="both", expand=True)

        self._style()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_welcome()

    # ---------- 外观 ----------

    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Body.TFrame", background="#ffffff")
        style.configure("TLabel", background="#ffffff", font=FONT)
        style.configure("Hint.TLabel", background="#ffffff", font=FONT_SMALL,
                        foreground="#666666")
        style.configure("Warn.TLabel", background="#ffffff", font=FONT_SMALL,
                        foreground="#c0392b")
        style.configure("Ok.TLabel", background="#ffffff", font=FONT_SMALL,
                        foreground="#1e8449")
        style.configure("Big.TButton", font=("Microsoft YaHei UI", 10))
        style.configure("Horizontal.TProgressbar", thickness=16)

    def _reset(self) -> None:
        for widget in self.body.winfo_children():
            widget.destroy()

    # ---------- 第 1 步：欢迎 + 环境检查 ----------

    def show_welcome(self) -> None:
        self.installing = False
        self._reset()

        ttk.Label(self.body, text="曼波配音工坊", font=FONT_TITLE).pack(anchor="w")
        ttk.Label(self.body, text="引擎安装向导", font=FONT_SUB).pack(anchor="w", pady=(0, 14))

        ttk.Label(
            self.body,
            text=("接下来安装 GPT-SoVITS v2Pro 本地推理引擎。\n"
                  "· 需要下载约 8.2 GB 整合包，解压后约 18 GB\n"
                  "· 请确保目标磁盘至少留出 32 GB 空间\n"
                  "· 安装路径必须是纯英文（GPT-SoVITS 不支持中文路径）"),
            justify="left",
        ).pack(anchor="w", pady=(0, 16))

        self.gpu_kind, self.gpu_name = detect_gpu()
        self.pkg_file = F_NVIDIA50 if self.gpu_kind == "nvidia50" else F_GENERAL
        if self.gpu_kind == "nvidia50":
            gpu_line = f"{self.gpu_name}（RTX 50 系，使用专用整合包）"
        elif self.gpu_kind == "general":
            gpu_line = f"{self.gpu_name}（使用通用整合包）"
        else:
            gpu_line = "未检测到 NVIDIA 显卡（只能用 CPU 推理，速度慢 20-50 倍）"

        pkg_gb = SIZE.get(self.pkg_file, 0) / 1024 ** 3
        try:
            find_7z()
            seven_line = "已找到 7-Zip 解压工具"
            seven_ok = True
        except InstallError:
            seven_line = "没有找到 7-Zip，安装到最后一步会失败（需要先装 7-Zip）"
            seven_ok = False

        table = ttk.Frame(self.body, style="Body.TFrame")
        table.pack(anchor="w", fill="x", pady=(0, 18))
        rows = [
            ("显卡", gpu_line),
            ("要下载", f"{self.pkg_file}（{pkg_gb:.1f} GB）"),
            ("解压工具", seven_line),
            ("Python", sys.version.split()[0]),
        ]
        for r, (key, value) in enumerate(rows):
            ttk.Label(table, text=key, font=FONT_SMALL,
                      foreground="#888888").grid(row=r, column=0, sticky="w", padx=(0, 14), pady=2)
            ttk.Label(table, text=value, font=FONT_SMALL,
                      foreground="#c0392b" if (not seven_ok and key == "解压工具") else "#222222",
                      wraplength=460, justify="left").grid(row=r, column=1, sticky="w", pady=2)

        bar = ttk.Frame(self.body, style="Body.TFrame")
        bar.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(bar, text="取消", command=self.on_close).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="下一步 →", style="Big.TButton",
                   command=self.show_choose).pack(side="right")

    # ---------- 第 2 步：选安装目录 ----------

    def show_choose(self) -> None:
        self._reset()

        ttk.Label(self.body, text="选择安装位置", font=FONT_SUB).pack(anchor="w", pady=(0, 6))
        ttk.Label(
            self.body,
            text="引擎会装到你指定的目录。建议放在空间充足的盘，路径保持纯英文。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(0, 12))

        row = ttk.Frame(self.body, style="Body.TFrame")
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=self.dest_var, font=FONT)
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(row, text="浏览…", command=self.browse_dir).pack(side="left", padx=(8, 0))

        self.space_label = ttk.Label(self.body, text="", style="Hint.TLabel")
        self.space_label.pack(anchor="w", pady=(10, 0))

        self.hint_label = ttk.Label(self.body, text="", style="Warn.TLabel", wraplength=640)
        self.hint_label.pack(anchor="w", pady=(4, 0))

        preset = ttk.Frame(self.body, style="Body.TFrame")
        preset.pack(anchor="w", fill="x", pady=(14, 0))
        ttk.Label(preset, text="快速选择：", style="Hint.TLabel").pack(side="left")
        for drive in ("F:", "D:", "E:", "C:"):
            if os.path.exists(drive + os.sep):
                ttk.Button(
                    preset, text=f"{drive} 盘",
                    command=lambda d=drive: self.dest_var.set(
                        os.path.join(d + os.sep, "MamboVoiceEngine", "GPT-SoVITS")),
                ).pack(side="left", padx=(6, 0))

        # 反复进出本页时不要重复挂监听
        if self._dest_trace_id is not None:
            try:
                self.dest_var.trace_remove("write", self._dest_trace_id)
            except Exception:
                pass
        self._dest_trace_id = self.dest_var.trace_add("write", lambda *_: self.refresh_space())
        self.refresh_space()

        bar = ttk.Frame(self.body, style="Body.TFrame")
        bar.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(bar, text="← 上一步", command=self.show_welcome).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="开始安装", style="Big.TButton",
                   command=self.start_install).pack(side="right")

    def browse_dir(self) -> None:
        picked = filedialog.askdirectory(
            title="选择引擎安装目录（纯英文路径）",
            initialdir=os.path.dirname(self.dest_var.get()) or os.path.splitdrive(ROOT)[0] + os.sep,
            mustexist=False,
        )
        if picked:
            self.dest_var.set(os.path.normpath(picked))

    def refresh_space(self) -> None:
        if not hasattr(self, "space_label"):
            return
        raw = self.dest_var.get().strip()
        if not raw:
            self.space_label.config(text="")
            if hasattr(self, "hint_label"):
                self.hint_label.config(text="")
            return

        drive = os.path.splitdrive(os.path.abspath(raw))[0]
        free_text = ""
        if drive and os.path.exists(drive + os.sep):
            try:
                free_gb = shutil.disk_usage(drive + os.sep).free / 1024 ** 3
                need = "够用" if free_gb >= MIN_FREE_GB else "空间不足"
                free_text = (f"{drive} 盘剩余 {free_gb:.1f} GB"
                             f"（安装需要约 {MIN_FREE_GB:.0f} GB，{need}）")
            except OSError:
                free_text = ""
        self.space_label.config(text=free_text)

        # 边输入边校验，别等到点「开始安装」才说不行
        if hasattr(self, "hint_label"):
            ok, msg = validate_target(raw)
            self.hint_label.config(text="" if ok else msg)

    # ---------- 第 3 步：安装进度 ----------

    def start_install(self) -> None:
        ok, msg = validate_target(self.dest_var.get())
        if not ok:
            self.hint_label.config(text=msg)
            return

        self.hint_label.config(text="")
        self.final_dest = os.path.abspath(self.dest_var.get().strip())
        self.installing = True
        self.cancel_event.clear()
        self._last_log = ""

        self._reset()
        ttk.Label(self.body, text="正在安装引擎", font=FONT_SUB).pack(anchor="w", pady=(0, 4))
        ttk.Label(self.body, text=self.final_dest, style="Hint.TLabel",
                  wraplength=640).pack(anchor="w", pady=(0, 14))

        self.progress = ttk.Progressbar(self.body, mode="determinate",
                                        maximum=100, value=0)
        self.progress.pack(fill="x", pady=(0, 8))

        ttk.Label(self.body, textvariable=self.stage_var).pack(anchor="w")
        ttk.Label(self.body, textvariable=self.speed_var,
                  style="Hint.TLabel").pack(anchor="w", pady=(2, 10))

        log_box = ttk.Frame(self.body, style="Body.TFrame")
        log_box.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_box, height=8, font=FONT_SMALL, bg="#f7f7f7",
                                relief="flat", wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)

        bar = ttk.Frame(self.body, style="Body.TFrame")
        bar.pack(side="bottom", fill="x", pady=(10, 0))
        self.cancel_btn = ttk.Button(bar, text="取消安装", command=self.request_cancel)
        self.cancel_btn.pack(side="right")

        threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(100, self._poll)

    def _worker(self) -> None:
        def emit(event: dict) -> None:
            self.queue.put(("progress", event))

        try:
            if looks_like_engine(self.final_dest):
                update_config(self.final_dest)
                self.queue.put(("done", self.final_dest))
                return

            emit({"phase": "prepare",
                  "text": f"显卡：{self.gpu_name}，准备下载 {self.pkg_file}"})
            pkg = download(
                self.pkg_file,
                dest_dir=download_dir_for(self.final_dest),
                on_progress=emit,
                cancel_event=self.cancel_event,
            )
            emit({"phase": "install", "text": "整合包就绪，开始解压安装…", "pct": 0.0})
            install(
                pkg=pkg,
                dest=self.final_dest,
                keep_pkg=False,
                on_progress=emit,
                cancel_event=self.cancel_event,
            )
            self.queue.put(("done", self.final_dest))
        except (DownloadCancelled, InstallCancelled):
            self.queue.put(("cancelled", None))
        except (DownloadError, InstallError) as e:
            self.queue.put(("error", str(e)))
        except Exception as e:  # 兜底，别让线程静默死掉
            self.queue.put(("error", f"{type(e).__name__}: {e}"))

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self._apply_progress(payload)  # type: ignore[arg-type]
                elif kind == "done":
                    self.show_done(True, str(payload))
                    return
                elif kind == "cancelled":
                    self.show_done(False, "已取消安装。\n已下载的整合包会保留，下次运行安装向导可以继续。")
                    return
                elif kind == "error":
                    self.show_done(False, str(payload))
                    return
        except queue.Empty:
            pass
        if self.installing:
            self.root.after(100, self._poll)

    def _apply_progress(self, event: dict) -> None:
        text = str(event.get("text") or "")
        if text:
            self.stage_var.set(text)
            if text != self._last_log:
                self._last_log = text
                self._append_log(f"[{time.strftime('%H:%M:%S')}] {text}")
        if "pct" in event:
            try:
                self.progress["value"] = float(event["pct"])
            except (TypeError, ValueError):
                pass
        speed = event.get("speed")
        eta = event.get("eta")
        if speed and eta:
            self.speed_var.set(
                f"{float(speed):.2f} MB/s · 预计还剩 {int(float(eta) // 60)} 分 {int(float(eta) % 60)} 秒")
        elif speed:
            self.speed_var.set(f"{float(speed):.2f} MB/s")

    def _append_log(self, line: str) -> None:
        if not hasattr(self, "log_text"):
            return
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def request_cancel(self) -> None:
        if not self.installing:
            return
        if messagebox.askyesno("取消安装", "确定要中止安装吗？\n已下载的整合包会保留，下次可以继续。"):
            self.cancel_event.set()
            self.cancel_btn.config(state="disabled", text="正在取消…")

    # ---------- 第 4 步：完成 / 失败 ----------

    def show_done(self, ok: bool, detail: str) -> None:
        self.installing = False
        self._reset()

        if ok:
            ttk.Label(self.body, text="安装完成", font=FONT_TITLE,
                      foreground="#1e8449").pack(anchor="w", pady=(0, 10))
            ttk.Label(self.body, text="引擎已经装好了，可以把音色模型放进 models 目录，\n"
                                      "然后双击「启动.bat」打开曼波配音工坊。",
                      justify="left").pack(anchor="w", pady=(0, 12))
            ttk.Label(self.body, text=f"安装位置：{detail}", style="Hint.TLabel",
                      wraplength=640).pack(anchor="w", pady=(0, 4))
            ttk.Label(self.body, text="音色模型获取方式见 models/README.md（仓库不含模型文件）",
                      style="Hint.TLabel").pack(anchor="w")
        else:
            ttk.Label(self.body, text="安装没有完成", font=FONT_TITLE,
                      foreground="#c0392b").pack(anchor="w", pady=(0, 10))
            ttk.Label(self.body, text=detail, style="Warn.TLabel",
                      wraplength=640, justify="left").pack(anchor="w", pady=(0, 8))
            ttk.Label(self.body, text="完整日志：logs/install.log", style="Hint.TLabel").pack(anchor="w")

        bar = ttk.Frame(self.body, style="Body.TFrame")
        bar.pack(side="bottom", fill="x", pady=(14, 0))
        if ok:
            ttk.Button(bar, text="打开安装目录",
                       command=lambda: self.open_folder(detail)).pack(side="right", padx=(8, 0))
            ttk.Button(bar, text="完成", command=self.root.destroy).pack(side="right")
        else:
            ttk.Button(bar, text="重试", command=self.show_choose).pack(side="right", padx=(8, 0))
            ttk.Button(bar, text="关闭", command=self.root.destroy).pack(side="right")

    def open_folder(self, path: str) -> None:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        try:
            if sys.platform == "win32":
                os.startfile(target)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception:
            pass

    def on_close(self) -> None:
        if self.installing:
            if not messagebox.askyesno("退出安装", "安装还没完成，确定要退出吗？\n已下载的部分会保留。"):
                return
            self.cancel_event.set()
        self.root.destroy()


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main() -> int:
    if not TK_OK:
        print("当前 Python 没有 tkinter，无法显示图形安装向导。")
        print("可以改用命令行方式：")
        print("  python tools/download_engine.py")
        print("  python tools/install_engine_local.py")
        return 2

    _enable_dpi_awareness()
    root = tk.Tk()
    InstallWizard(root)
    root.update_idletasks()
    w, h = 720, 560
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
