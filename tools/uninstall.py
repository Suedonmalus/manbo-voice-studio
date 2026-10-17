"""卸载曼波配音工坊：删掉安装时创建的引擎、缓存、音色模型，并清理配置。

用法：
    python tools/uninstall.py              # 图形卸载向导
    python tools/uninstall.py --dry-run    # 只列出会删什么，不动手
    python tools/uninstall.py --yes        # 命令行直接卸载（供 AI Agent 调用）

**不会删除**：
    - output/ 里你自己生成的音频和字幕
    - 项目源码、core/ ui/ tools/
    - 系统里 pip 装的 Python 库（可能与别的项目共用）

安全护栏：只有在目录里同时找到 api.py 和 runtime/（确认是引擎）时才会删除整个目录，
配置被改到奇怪位置时不会跟着乱删。
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import socket
import sys
import threading
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TK_OK = True
try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except Exception:
    TK_OK = False

from tools.install_engine_local import (  # noqa: E402
    default_dest,
    install_dir_for_download,
    looks_like_engine,
)

CONFIG_PATH = os.path.join(ROOT, "config.json")
MODEL_FILES = ("manbo_e8_s168.pth", "manbo-e10.ckpt", "refer.wav")
FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 18, "bold")


@dataclass
class Target:
    key: str
    label: str
    path: str
    kind: str                 # dir / file
    exists: bool
    size: int
    removable: bool
    note: str = ""

    @property
    def size_text(self) -> str:
        if not self.exists:
            return "—"
        return human_size(self.size)


def human_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def read_engine_dir() -> str:
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            value = (data.get("engine_dir") or "").strip()
            if value:
                return value
        except Exception:
            pass
    return default_dest()


def engine_port_busy(host: str = "127.0.0.1", port: int = 9880,
                     timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_plan(remove_models: bool = True,
               remove_7zr: bool = True,
               engine_dir: str | None = None,
               calc_size: bool = True) -> list[Target]:
    """列出所有安装痕迹。calc_size=False 时 size 先记 0，由调用方异步补算。"""
    engine_dir = os.path.abspath(engine_dir or read_engine_dir() or default_dest())
    parent = os.path.dirname(engine_dir)
    drive_root = os.path.splitdrive(engine_dir)[0] + os.sep
    targets: list[Target] = []

    def probe(key: str, label: str, path: str, kind: str,
              must_be_engine: bool = False) -> Target:
        exists = os.path.isdir(path) if kind == "dir" else os.path.isfile(path)
        if not exists:
            return Target(key, label, path, kind, False, 0, False, "不存在")
        size = 0
        if calc_size:
            size = dir_size(path) if kind == "dir" else os.path.getsize(path)
        removable = True
        note = ""
        if must_be_engine and not looks_like_engine(path):
            removable = False
            note = "没有 api.py + runtime，不像是引擎，已跳过"
        return Target(key, label, path, kind, True, size, removable, note)

    targets.append(probe("engine", "GPT-SoVITS 引擎", engine_dir, "dir",
                         must_be_engine=True))
    targets.append(probe("voices", "参考音频副本", os.path.join(parent, "voices"), "dir"))
    targets.append(probe("engine_logs", "引擎运行日志", os.path.join(parent, "logs"), "dir"))
    targets.append(probe("download", "整合包下载缓存",
                         install_dir_for_download(engine_dir), "dir"))
    alt_dl = os.path.join(drive_root, "_mambo_download")
    if alt_dl != install_dir_for_download(engine_dir):
        targets.append(probe("download_alt", "整合包下载缓存（备用位置）", alt_dl, "dir"))
    targets.append(probe("engine_temp", "项目内下载缓存",
                         os.path.join(ROOT, "engine_temp"), "dir"))

    for name in MODEL_FILES:
        path = os.path.join(ROOT, "models", name)
        if os.path.isfile(path):
            t = probe("model_" + name, f"音色模型 {name}", path, "file")
            if not remove_models:
                t.removable = False
                t.note = "已选择保留"
            targets.append(t)

    path_7zr = os.path.join(ROOT, "tools", "7zr.exe")
    if os.path.isfile(path_7zr):
        t = probe("7zr", "7zr.exe（安装时下载）", path_7zr, "file")
        if not remove_7zr:
            t.removable = False
            t.note = "已选择保留"
        targets.append(t)

    return targets


def _drop_engine_dir_from_config() -> None:
    if not os.path.isfile(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    if "engine_dir" not in data:
        return
    del data["engine_dir"]
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _prune_empty_parent(parent: str) -> None:
    """MamboVoiceEngine 空了就顺手删掉它自己。"""
    try:
        if os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
    except OSError:
        pass


def execute(plan: list[Target],
            update_config: bool = True,
            on_progress=None) -> dict:
    removed: list[str] = []
    failed: list[dict] = []
    freed = 0
    engine_dir = ""

    for t in plan:
        if t.key == "engine":
            engine_dir = t.path
        if not t.exists or not t.removable:
            continue
        if on_progress:
            on_progress(f"正在删除：{t.label}")
        try:
            if t.kind == "dir":
                shutil.rmtree(t.path)
            else:
                os.remove(t.path)
            removed.append(t.path)
            freed += t.size
        except OSError as e:
            failed.append({"path": t.path, "error": f"{type(e).__name__}: {e}"})

    if engine_dir:
        if update_config and not os.path.isdir(engine_dir):
            _drop_engine_dir_from_config()
        _prune_empty_parent(os.path.dirname(engine_dir))

    return {"removed": removed, "failed": failed, "freed": freed}


# ---------------------------------------------------------------- 命令行

def run_console(remove_models: bool, remove_7zr: bool,
                dry_run: bool, assume_yes: bool, as_json: bool) -> int:
    if engine_port_busy():
        print("[警告] 检测到引擎还在运行（127.0.0.1:9880）。请先关闭曼波配音工坊再卸载。",
              file=sys.stderr)

    plan = build_plan(remove_models=remove_models, remove_7zr=remove_7zr)
    rows = [t for t in plan if t.exists]
    if not rows:
        payload = {"ok": True, "removed": [], "failed": [], "freed": 0,
                   "note": "没有发现需要卸载的内容"}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not as_json:
        print("将要删除：")
        for t in rows:
            flag = "" if t.removable else "  [跳过]"
            print(f"  {t.size_text:>10}  {t.path}{flag}{('  ' + t.note) if t.note else ''}")
        print(f"合计约 {human_size(sum(t.size for t in rows if t.removable))}")
        print()
        print("不会删除：output/ 里生成的音频、项目源码、pip 安装的 Python 库。")

    if dry_run:
        payload = {"ok": True, "dry_run": True,
                   "would_remove": [t.path for t in rows if t.removable],
                   "freed": sum(t.size for t in rows if t.removable)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not assume_yes:
        print()
        answer = input("确认卸载？输入 yes 继续（其他任意键取消）：").strip().lower()
        if answer != "yes":
            print("已取消，什么都没删。")
            return 1

    result = execute(plan, on_progress=lambda m: print(m, file=sys.stderr))
    payload = {
        "ok": not result["failed"],
        "removed": result["removed"],
        "failed": result["failed"],
        "freed": result["freed"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if result["failed"]:
        print("[警告] 有文件没删掉（可能被占用），请关闭软件后重试。", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------- 图形界面

class UninstallWizard:
    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.root.title("曼波配音工坊 · 卸载")
        self.root.resizable(False, False)
        self.root.configure(bg="#ffffff")

        self.remove_models = tk.BooleanVar(value=True)
        self.remove_7zr = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="")
        self.busy = False
        self.result: dict | None = None
        self.engine_dir = read_engine_dir()
        self.q: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._polling = False

        self.body = ttk.Frame(root, padding=(24, 18, 24, 16), style="Body.TFrame")
        self.body.pack(fill="both", expand=True)
        self._style()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_list()

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
        style.configure("Treeview", rowheight=24, font=FONT_SMALL)
        style.configure("Treeview.Heading", font=FONT_SMALL)

    def _reset(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()

    def show_list(self) -> None:
        self._reset()
        self.busy = False

        ttk.Label(self.body, text="卸载曼波配音工坊", font=FONT_TITLE).pack(anchor="w")
        ttk.Label(
            self.body,
            text="下面这些是安装时创建的内容。卸载会删掉它们，但保留你自己生成的音频和项目源码。",
            style="Hint.TLabel", wraplength=700, justify="left",
        ).pack(anchor="w", pady=(6, 10))

        if engine_port_busy():
            ttk.Label(self.body,
                      text="⚠ 检测到引擎还在运行（127.0.0.1:9880）。请先关闭曼波配音工坊，否则文件会被占用删不掉。",
                      style="Warn.TLabel", wraplength=700).pack(anchor="w", pady=(0, 8))

        box = ttk.Frame(self.body, style="Body.TFrame")
        box.pack(fill="both", expand=True)

        columns = ("label", "path", "size", "state")
        self.tree = ttk.Treeview(box, columns=columns, show="headings", height=9)
        for col, title, width, anchor in (
            ("label", "项目", 150, "w"),
            ("path", "路径", 330, "w"),
            ("size", "大小", 90, "e"),
            ("state", "状态", 110, "w"),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "path"))
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        opts = ttk.Frame(self.body, style="Body.TFrame")
        opts.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(opts, text="同时删除音色模型（约 230MB，删了要重新获取）",
                        variable=self.remove_models,
                        command=self._rebuild).pack(anchor="w")
        ttk.Checkbutton(opts, text="同时删除 tools/7zr.exe（安装时自动下载的解压工具）",
                        variable=self.remove_7zr,
                        command=self._rebuild).pack(anchor="w")

        ttk.Label(self.body,
                  text="不会删除：output/ 里你生成的音频和字幕、项目源码、系统里的 Python 库。",
                  style="Hint.TLabel").pack(anchor="w", pady=(8, 0))

        bar = ttk.Frame(self.body, style="Body.TFrame")
        bar.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(bar, text="取消", command=self.on_close).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="开始卸载", command=self.confirm_uninstall).pack(side="right")

        self._rebuild()

    def _rebuild(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.plan = build_plan(remove_models=self.remove_models.get(),
                               remove_7zr=self.remove_7zr.get(),
                               engine_dir=self.engine_dir,
                               calc_size=False)
        for t in self.plan:
            state = ("待删除" if t.removable else ("未安装" if not t.exists else t.note))
            self.tree.insert("", "end", iid=t.key,
                             values=(t.label, t.path, "计算中…", state))
        # 磁盘遍历比较慢，放后台算，别卡住窗口
        self._ensure_polling()
        threading.Thread(target=self._size_worker, args=(list(self.plan),),
                         daemon=True).start()

    def _ensure_polling(self) -> None:
        if self._polling:
            return
        self._polling = True
        self.root.after(120, self._poll)

    def _poll(self) -> None:
        """只在主线程碰 Tk；后台线程一律往队列里丢事件。"""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "size":
                    key, size = payload  # type: ignore[misc]
                    self._set_size(key, size)
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "done":
                    self._polling = False
                    self.show_done(payload)  # type: ignore[arg-type]
                    return
        except queue.Empty:
            pass
        try:
            self.root.after(120, self._poll)
        except Exception:
            self._polling = False

    def _size_worker(self, plan: list[Target]) -> None:
        for t in plan:
            if not t.exists:
                continue
            try:
                size = dir_size(t.path) if t.kind == "dir" else os.path.getsize(t.path)
            except OSError:
                continue
            self.q.put(("size", (t.key, size)))

    def _set_size(self, key: str, size: int) -> None:
        try:
            values = list(self.tree.item(key, "values"))
            if len(values) >= 4:
                values[2] = human_size(size)
                self.tree.item(key, values=values)
            for t in self.plan:
                if t.key == key:
                    t.size = size
        except Exception:
            pass

    def confirm_uninstall(self) -> None:
        if self.busy:
            return
        targets = [t for t in self.plan if t.exists and t.removable]
        if not targets:
            messagebox.showinfo("没有可卸载的内容", "没找到安装时创建的文件。")
            return
        has_engine = any(t.key == "engine" for t in targets)
        msg = ("确定要卸载吗？\n\n"
               f"将删除 {len(targets)} 项，释放约 {human_size(sum(t.size for t in targets))}。\n")
        if has_engine:
            msg += "\n引擎（约 14GB）删掉后，软件就打不开了，要重新装才能用。\n"
        msg += "\n这个操作不可撤销。"
        if not messagebox.askyesno("确认卸载", msg, icon="warning", default="no"):
            return
        self.run_uninstall()

    def run_uninstall(self) -> None:
        self.busy = True
        self._reset()
        ttk.Label(self.body, text="正在卸载…", font=FONT_TITLE).pack(anchor="w", pady=(0, 10))
        ttk.Label(self.body, textvariable=self.status_var,
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 6))
        self.status_var.set("准备中…")
        self.pb = ttk.Progressbar(self.body, mode="indeterminate")
        self.pb.pack(fill="x", pady=(0, 10))
        self.pb.start(12)

        plan = [t for t in self.plan if t.removable]
        threading.Thread(target=self._worker, args=(plan,), daemon=True).start()

    def _worker(self, plan: list[Target]) -> None:
        def progress(msg: str) -> None:
            self.q.put(("status", msg))

        result = execute(plan, on_progress=progress)
        self.q.put(("done", result))

    def show_done(self, result: dict) -> None:
        self.busy = False
        try:
            self.pb.stop()
        except Exception:
            pass
        self._reset()
        ok = not result["failed"]
        ttk.Label(self.body,
                  text="卸载完成" if ok else "卸载完成，但有文件没删掉",
                  font=FONT_TITLE,
                  foreground="#1e8449" if ok else "#c0392b").pack(anchor="w", pady=(0, 10))
        ttk.Label(self.body,
                  text=f"已删除 {len(result['removed'])} 项，释放约 {human_size(result['freed'])}。",
                  ).pack(anchor="w", pady=(0, 6))
        if result["failed"]:
            ttk.Label(self.body,
                      text="以下路径删除失败（通常是被占用，关掉软件和引擎后重试）：",
                      style="Warn.TLabel").pack(anchor="w", pady=(6, 4))
            for item in result["failed"][:8]:
                ttk.Label(self.body, text=f"  {item['path']}",
                          style="Warn.TLabel", wraplength=700).pack(anchor="w")
        else:
            ttk.Label(self.body,
                      text="config.json 里的引擎路径已经清空。想重新用的话，再运行一次「安装引擎.bat」即可。",
                      style="Hint.TLabel", wraplength=700, justify="left").pack(anchor="w")
        ttk.Label(self.body,
                  text="output/ 里你生成的音频和项目源码都还在，没有被删。",
                  style="Hint.TLabel").pack(anchor="w", pady=(8, 0))

        bar = ttk.Frame(self.body, style="Body.TFrame")
        bar.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(bar, text="完成", command=self.root.destroy).pack(side="right")

    def on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno("正在卸载", "卸载还没完成，确定要退出吗？"):
                return
        self.root.destroy()


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="卸载曼波配音工坊的引擎与安装产物")
    ap.add_argument("--dry-run", action="store_true", help="只列出会删什么，不删除")
    ap.add_argument("--yes", action="store_true", help="跳过确认直接卸载（供 Agent 使用）")
    ap.add_argument("--console", action="store_true", help="强制使用命令行模式")
    ap.add_argument("--keep-models", action="store_true", help="保留音色模型")
    ap.add_argument("--keep-7zr", action="store_true", help="保留 tools/7zr.exe")
    ap.add_argument("--json", action="store_true", help="只输出 JSON 结果")
    args = ap.parse_args(argv)

    use_console = (args.console or args.dry_run or args.yes or not TK_OK)
    if use_console:
        return run_console(
            remove_models=not args.keep_models,
            remove_7zr=not args.keep_7zr,
            dry_run=args.dry_run,
            assume_yes=args.yes,
            as_json=args.json,
        )

    _enable_dpi_awareness()
    root = tk.Tk()
    UninstallWizard(root)
    root.update_idletasks()
    w, h = 780, 600
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
