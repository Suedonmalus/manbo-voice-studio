"""曼波配音工坊 —— 程序入口。

用法：
    python app.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    # 高分屏与渲染后端设置必须在导入 Qt 之前完成
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("缺少 PySide6，请先运行：pip install -r requirements.txt")
        return 1

    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("曼波配音工坊")
    app.setFont(QFont("Microsoft YaHei UI", 10))

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


def _write_crash_log(exc: BaseException) -> None:
    import traceback
    log_dir = os.path.join(ROOT, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "app.log"), "a", encoding="utf-8") as f:
            f.write(f"\n===== {__import__('time').strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except OSError:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 用 pythonw 启动时没有控制台，异常写入 logs/app.log
        _write_crash_log(exc)
        raise
