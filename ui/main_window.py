"""主窗口：文案输入 → 合成 → 试听 → 导出 WAV + SRT。"""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from core import config as cfg_module
from core.config import Settings, resolve_engine_dir, resolve_voice
from core.engine_client import TTSClient
from core.engine_manager import EngineManager, is_installed, LOG_DIR
from core.segmenter import split_sentences
from core.synthesizer import SynthRequest, SynthResult, SynthesisError, auto_basename, synthesize
from ui import theme

PLACEHOLDER = (
    "在这里输入要配音的文案，例如：\n\n"
    "曼波，曼波，祭典曼波！嘿唷曼波，祭典曼波，清清凉凉，摇摇摆摆，祭典曼波！\n\n"
    "支持直接粘贴整篇脚本，软件会按标点自动断句，逐句合成后再拼接成一条完整音轨。"
)

SAMPLE = (
    "我宣布个事：从今天起，我要做一个讲道理的曼波。\n"
    "第一，谁再喊我胖，我就拿浮力原理给他上一课。\n"
    "第二，干完活必须吃米饭，这是鲸类的基本权益。\n"
    "第三，以上两条随时可以被我推翻——毕竟我是曼波。"
)


# ---------------------------------------------------------------- 后台任务
class SynthWorker(QObject):
    log = Signal(str, str)
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, req: SynthRequest, api_url: str, manager: EngineManager,
                 cancel_evt: threading.Event, auto_start: bool = True):
        super().__init__()
        self.req = req
        self.api_url = api_url
        self.manager = manager
        self.cancel_evt = cancel_evt
        self.auto_start = auto_start

    def _cancelled(self) -> bool:
        return self.cancel_evt.is_set()

    def run(self) -> None:
        try:
            client = TTSClient(self.api_url)
            if not client.is_online():
                if not self.auto_start:
                    self.failed.emit("引擎未启动。点右上角「启动引擎」，或勾选「生成时自动启动引擎」。")
                    return
                self.log.emit("WARNING", "引擎不在线，正在启动本地 GPT-SoVITS 服务…")
                ok, msg = self.manager.start(
                    api_url=self.api_url,
                    sovits=self.req.voice.sovits,
                    gpt=self.req.voice.gpt,
                    ref_wav=self.req.voice.ref_wav,
                    ref_text=self.req.voice.ref_text,
                )
                if not ok:
                    self.failed.emit(msg)
                    return
                if not self.manager.wait_online(self.api_url, 180.0, self._cancelled):
                    self.failed.emit("引擎启动超时。请看 logs/engine.log 末尾的报错。")
                    return
                self.log.emit("INFO", "引擎已就绪")

            result = synthesize(
                self.req, client,
                log_cb=lambda lv, m: self.log.emit(lv, m),
                progress_cb=lambda d, t, p: self.progress.emit(d, t, p),
                cancel_cb=self._cancelled,
            )
            self.done.emit(result)
        except SynthesisError as e:
            self.failed.emit(str(e))
        except Exception as e:  # 兜底：不让后台线程静默死掉
            self.failed.emit(f"{type(e).__name__}: {e}")


class EngineStartWorker(QObject):
    log = Signal(str, str)
    finished = Signal(bool, str)

    def __init__(self, api_url: str, manager: EngineManager, voice):
        super().__init__()
        self.api_url = api_url
        self.manager = manager
        self.voice = voice

    def run(self) -> None:
        client = TTSClient(self.api_url)
        if client.is_online():
            self.finished.emit(True, "引擎已在线")
            return
        ok, msg = self.manager.start(
            api_url=self.api_url, sovits=self.voice.sovits, gpt=self.voice.gpt,
            ref_wav=self.voice.ref_wav, ref_text=self.voice.ref_text,
        )
        if not ok:
            self.finished.emit(False, msg)
            return
        self.log.emit("INFO", "引擎进程已拉起，等待模型加载（首次约 10-30 秒）…")
        ok = self.manager.wait_online(self.api_url, 180.0)
        self.finished.emit(ok, "引擎已就绪" if ok else "引擎启动超时，请看 logs/engine.log")


# ---------------------------------------------------------------- 主窗口
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.manager = EngineManager()
        self.voices = cfg_module.discover_voices()
        self.cancel_evt = threading.Event()
        self.thread: QThread | None = None
        self.worker: SynthWorker | None = None
        self.engine_thread: QThread | None = None
        self.current_result: SynthResult | None = None
        self._last_dir = self.settings.output_dir or os.path.join(cfg_module.ROOT, "output")

        self._build_ui()
        self._apply_theme()
        self._wire()

        self._log("INFO", "曼波配音工坊已启动")
        if not is_installed():
            self._log("WARNING", "尚未检测到引擎。请先运行「安装引擎.bat」下载 GPT-SoVITS 整合包。")
        self._refresh_engine_status()
        self._update_stats()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_engine_status)
        self.timer.start(5000)

    # ------------------------------------------------------------ 构建界面
    def _build_ui(self) -> None:
        self.setWindowTitle("曼波配音工坊 v1.0")
        self.resize(1180, 840)
        self.setMinimumSize(980, 700)

        root = QWidget(objectName="Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(16, 12, 16, 14)
        body_lay.setSpacing(10)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_text_panel())
        split.addWidget(self._build_param_panel())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([740, 380])
        split.setChildrenCollapsible(False)
        body_lay.addWidget(split, 1)

        body_lay.addWidget(self._build_action_bar())
        body_lay.addWidget(self._build_player_bar())
        body_lay.addWidget(self._build_log_panel())
        outer.addWidget(body, 1)

    def _build_header(self) -> QWidget:
        header = QWidget(objectName="Header")
        header.setFixedHeight(62)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 8, 18, 8)
        lay.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        t = QLabel("曼波配音工坊", objectName="Title")
        s = QLabel("文字 → 曼波语音（WAV） + 字幕（SRT）   ·   本地 GPT-SoVITS 推理，离线可用", objectName="Subtitle")
        title_box.addWidget(t)
        title_box.addWidget(s)
        lay.addLayout(title_box)
        lay.addStretch(1)

        self.dot = QLabel("●", objectName="StatusDot")
        self.status_label = QLabel("检测中…", objectName="Meta")
        self.btn_engine = QPushButton("启动引擎")
        self.btn_engine.setFixedHeight(32)
        self.btn_theme = QPushButton("主题")
        self.btn_theme.setFixedSize(52, 32)
        self.btn_theme.setToolTip("切换深浅主题")

        lay.addWidget(self.dot)
        lay.addWidget(self.status_label)
        lay.addSpacing(6)
        lay.addWidget(self.btn_engine)
        lay.addWidget(self.btn_theme)
        return header

    def _build_text_panel(self) -> QWidget:
        box = QGroupBox("配音文案")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(8)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(PLACEHOLDER)
        self.text_edit.setAcceptDrops(True)
        self.text_edit.setTabChangesFocus(True)
        lay.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
        self.meta_label = QLabel("0 字 · 0 句", objectName="Meta")
        row.addWidget(self.meta_label)
        row.addStretch(1)
        btn_clear = QPushButton("清空")
        btn_clear.setFixedHeight(30)
        btn_sample = QPushButton("填入示例")
        btn_sample.setFixedHeight(30)
        btn_import = QPushButton("导入 TXT")
        btn_import.setFixedHeight(30)
        row.addWidget(btn_clear)
        row.addWidget(btn_sample)
        row.addWidget(btn_import)
        lay.addLayout(row)

        btn_clear.clicked.connect(self._clear_text)
        btn_sample.clicked.connect(lambda: self.text_edit.setPlainText(SAMPLE))
        btn_import.clicked.connect(self._import_txt)
        return box

    def _build_param_panel(self) -> QWidget:
        box = QGroupBox("合成参数")
        box.setMinimumWidth(360)
        box.setMaximumWidth(420)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(12)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        r = 0
        grid.addWidget(QLabel("音色"), r, 0)
        self.voice_combo = QComboBox()
        if self.voices:
            self.voice_combo.addItems(list(self.voices.keys()))
            idx = self.voice_combo.findText(self.settings.voice)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)
        else:
            self.voice_combo.addItem("（未检测到音色模型）")
        grid.addWidget(self.voice_combo, r, 1)
        r += 1

        self.speed_slider, self.speed_value, sp_row = self._slider_row(
            10, 300, int(self.settings.speed * 100), "1.00x")
        grid.addWidget(QLabel("语速"), r, 0)
        grid.addLayout(sp_row, r, 1)
        r += 1

        self.gap_slider, self.gap_value, gp_row = self._slider_row(
            0, 150, int(self.settings.gap_seconds * 100), f"{self.settings.gap_seconds:.2f}s")
        grid.addWidget(QLabel("句间停顿"), r, 0)
        grid.addLayout(gp_row, r, 1)
        r += 1

        self.vol_slider, self.vol_value, v_row = self._slider_row(
            -20, 12, int(self.settings.volume_db), "0 dB")
        grid.addWidget(QLabel("音量"), r, 0)
        grid.addLayout(v_row, r, 1)
        r += 1

        grid.addWidget(QLabel("字幕每行"), r, 0)
        self.sub_chars = QSpinBox()
        self.sub_chars.setRange(0, 60)
        self.sub_chars.setValue(self.settings.subtitle_max_chars)
        self.sub_chars.setSuffix(" 字")
        self.sub_chars.setToolTip("单行字幕最多字数，0 表示按整句不拆分")
        grid.addWidget(self.sub_chars, r, 1)
        r += 1

        self.normalize_check = QCheckBox("峰值归一化（推荐）")
        self.normalize_check.setChecked(self.settings.normalize)
        grid.addWidget(self.normalize_check, r, 0, 1, 2)
        r += 1

        self.autostart_check = QCheckBox("生成时自动启动引擎")
        self.autostart_check.setChecked(self.settings.auto_start_engine)
        grid.addWidget(self.autostart_check, r, 0, 1, 2)
        r += 1

        lay.addLayout(grid)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #2A2E3A;")
        lay.addWidget(line)

        lay.addWidget(QLabel("保存目录"))
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(self._last_dir)
        btn_dir = QPushButton("浏览…")
        btn_dir.setFixedWidth(72)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(btn_dir)
        lay.addLayout(dir_row)

        lay.addWidget(QLabel("文件名"))
        self.name_edit = QLineEdit(self.settings.filename)
        self.name_edit.setPlaceholderText("留空则取文案开头")
        lay.addWidget(self.name_edit)

        lay.addStretch(1)

        btn_dir.clicked.connect(self._choose_dir)
        self.speed_slider.valueChanged.connect(
            lambda v: self.speed_value.setText(f"{v / 100:.2f}x"))
        self.gap_slider.valueChanged.connect(
            lambda v: self.gap_value.setText(f"{v / 100:.2f}s"))
        self.vol_slider.valueChanged.connect(lambda v: self.vol_value.setText(f"{v} dB"))
        return box

    @staticmethod
    def _slider_row(lo: int, hi: int, val: int, text: str):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(val)
        value = QLabel(text, objectName="ValueLabel")
        value.setFixedWidth(56)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(slider, 1)
        row.addWidget(value)
        return slider, value, row

    def _build_action_bar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.btn_generate = QPushButton("生成配音", objectName="Primary")
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setFixedHeight(38)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setFixedWidth(260)
        self.progress.setFixedHeight(20)

        self.phase_label = QLabel("待命", objectName="Meta")

        lay.addWidget(self.btn_generate)
        lay.addWidget(self.btn_cancel)
        lay.addSpacing(6)
        lay.addWidget(self.progress)
        lay.addWidget(self.phase_label, 1)
        return bar

    def _build_player_bar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.audio_out = QAudioOutput()
        self.audio_out.setVolume(0.9)
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_out)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(38, 34)
        self.btn_play.setEnabled(False)
        self.btn_play.setToolTip("试听生成结果")

        self.pos_slider = QSlider(Qt.Horizontal)
        self.pos_slider.setRange(0, 1000)
        self.pos_slider.setValue(0)
        self.pos_slider.setEnabled(False)

        self.time_label = QLabel("00:00 / 00:00", objectName="Meta")
        self.time_label.setMinimumWidth(110)

        self.btn_open_dir = QPushButton("打开目录")
        self.btn_open_dir.setFixedHeight(34)
        self.btn_open_srt = QPushButton("打开字幕")
        self.btn_open_srt.setFixedHeight(34)
        self.btn_open_dir.setEnabled(False)
        self.btn_open_srt.setEnabled(False)

        lay.addWidget(self.btn_play)
        lay.addWidget(self.pos_slider, 1)
        lay.addWidget(self.time_label)
        lay.addWidget(self.btn_open_dir)
        lay.addWidget(self.btn_open_srt)
        return bar

    def _build_log_panel(self) -> QWidget:
        box = QGroupBox("运行日志")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 6, 10, 8)
        self.log_view = QPlainTextEdit(objectName="LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(150)
        self.log_view.setMaximumBlockCount(600)
        lay.addWidget(self.log_view)
        return box

    # ------------------------------------------------------------ 连接
    def _wire(self) -> None:
        self.btn_generate.clicked.connect(self._on_generate)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_engine.clicked.connect(self._on_start_engine)
        self.btn_theme.clicked.connect(self._toggle_theme)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_open_dir.clicked.connect(self._open_dir)
        self.btn_open_srt.clicked.connect(self._open_srt)
        self.pos_slider.sliderMoved.connect(self._seek)
        self.pos_slider.sliderReleased.connect(
            lambda: self.player.setPosition(self.pos_slider.value()))
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_play_state)
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.text_edit.installEventFilter(self)

        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.timeout.connect(self._update_stats)

    # ------------------------------------------------------------ 文本
    def _on_text_changed(self) -> None:
        self._stats_timer.start(180)

    def _update_stats(self) -> None:
        text = self.text_edit.toPlainText()
        char_count = len(text.strip())
        sentences = split_sentences(text) if text.strip() else []
        self.meta_label.setText(f"{char_count} 字 · {len(sentences)} 句")

    def _clear_text(self) -> None:
        self.text_edit.clear()

    def _import_txt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入文案", "", "文本文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(path, "r", encoding=enc) as f:
                    self.text_edit.setPlainText(f.read())
                self._log("INFO", f"已导入 {os.path.basename(path)}")
                return
            except UnicodeDecodeError:
                continue
            except OSError as e:
                self._log("ERROR", f"读取失败：{e}")
                return
        self._log("ERROR", "无法识别文件编码，请转成 UTF-8 后重试")

    def eventFilter(self, obj, event):
        # 文本区支持拖入 txt 文件
        if obj is self.text_edit and event.type() == event.Type.Drop:
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if path.lower().endswith(".txt"):
                    try:
                        for enc in ("utf-8-sig", "utf-8", "gbk"):
                            try:
                                with open(path, "r", encoding=enc) as f:
                                    self.text_edit.setPlainText(f.read())
                                self._log("INFO", f"已拖入 {os.path.basename(path)}")
                                return True
                            except UnicodeDecodeError:
                                continue
                    except OSError:
                        pass
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------ 参数
    def _choose_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    def _toggle_theme(self) -> None:
        self.settings.dark_theme = not self.settings.dark_theme
        self._apply_theme()
        self.settings.save()

    def _apply_theme(self) -> None:
        self.setStyleSheet(theme.stylesheet(self.settings.dark_theme))
        self.btn_theme.setToolTip("切换到浅色主题" if self.settings.dark_theme else "切换到深色主题")

    # ------------------------------------------------------------ 合成
    def _collect_settings(self) -> None:
        self.settings.speed = self.speed_slider.value() / 100.0
        self.settings.gap_seconds = self.gap_slider.value() / 100.0
        self.settings.volume_db = float(self.vol_slider.value())
        self.settings.subtitle_max_chars = self.sub_chars.value()
        self.settings.normalize = self.normalize_check.isChecked()
        self.settings.auto_start_engine = self.autostart_check.isChecked()
        self.settings.output_dir = self.dir_edit.text().strip()
        self.settings.filename = self.name_edit.text().strip()
        self.settings.voice = self.voice_combo.currentText()
        self.settings.save()

    def _on_generate(self) -> None:
        if self.thread is not None:
            return
        text = self.text_edit.toPlainText().strip()
        if not text:
            self._log("WARNING", "文案是空的，先写点东西吧。")
            self.text_edit.setFocus()
            return

        voice_name = self.voice_combo.currentText()
        voice = resolve_voice(voice_name)
        if voice is None:
            self._log("ERROR", "没有可用音色：models/ 目录下缺少 .pth/.ckpt/参考音频。")
            return

        self._collect_settings()
        out_dir = self.settings.output_dir or self._last_dir
        req = SynthRequest(
            text=text,
            voice=voice,
            output_dir=out_dir,
            basename=self.settings.filename or auto_basename(text),
            speed=self.settings.speed,
            gap_seconds=self.settings.gap_seconds,
            subtitle_max_chars=self.settings.subtitle_max_chars,
            normalize=self.settings.normalize,
            volume_db=self.settings.volume_db,
        )

        self.cancel_evt.clear()
        self.progress.setValue(0)
        self.phase_label.setText("准备中…")
        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_play.setEnabled(False)
        self.player.stop()

        self.worker = SynthWorker(req, self.settings.api_url, self.manager, self.cancel_evt,
                                  auto_start=self.settings.auto_start_engine)
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.done.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup_thread)
        self.thread.start()

    def _on_cancel(self) -> None:
        if self.thread is None:
            return
        self._log("WARNING", "正在取消…")
        self.cancel_evt.set()
        self.btn_cancel.setEnabled(False)

    def _on_progress(self, done: int, total: int, phase: str) -> None:
        pct = int(done / total * 100) if total else 0
        self.progress.setValue(pct)
        self.phase_label.setText(phase)

    def _on_done(self, result: SynthResult) -> None:
        self.current_result = result
        self.progress.setValue(100)
        self.phase_label.setText(f"完成 · {result.duration:.1f} 秒")
        self.btn_play.setEnabled(True)
        self.btn_open_dir.setEnabled(True)
        self.btn_open_srt.setEnabled(True)
        self.player.setSource(QUrl.fromLocalFile(result.wav_path))
        self._log("INFO", f"WAV → {result.wav_path}")
        self._log("INFO", f"SRT → {result.srt_path}")

    def _on_failed(self, message: str) -> None:
        self.progress.setValue(0)
        self.phase_label.setText("失败")
        self._log("ERROR", message)

    def _cleanup_thread(self) -> None:
        if self.thread is not None:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.btn_generate.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._refresh_engine_status()

    # ------------------------------------------------------------ 引擎
    def _refresh_engine_status(self) -> None:
        if not is_installed():
            self.dot.setStyleSheet("color: #F0743A;")
            self.status_label.setText("引擎未安装")
            self.btn_engine.setText("如何安装")
            return
        online = TTSClient(self.settings.api_url).is_online(timeout=0.8)
        if online:
            self.dot.setStyleSheet("color: #4ADE80;")
            self.status_label.setText("引擎就绪")
        else:
            self.dot.setStyleSheet("color: #F5C451;")
            self.status_label.setText("引擎未启动")
        self.btn_engine.setText("启动引擎")

    def _on_start_engine(self) -> None:
        if not is_installed():
            self._log("WARNING",
                      "引擎尚未安装：双击「安装引擎.bat」自动下载并解压整合包（约 8.2GB），"
                      "或手动把整合包解压到 engine/GPT-SoVITS/。")
            self._log("INFO", f"引擎目录：{resolve_engine_dir()}")
            return
        if self.engine_thread is not None:
            return

        voice = resolve_voice(self.voice_combo.currentText())
        if voice is None:
            self._log("ERROR", "没有可用音色模型，无法启动引擎。")
            return

        self.btn_engine.setEnabled(False)
        self.status_label.setText("启动中…")
        self.dot.setStyleSheet("color: #F5C451;")

        worker = EngineStartWorker(self.settings.api_url, self.manager, voice)
        self.engine_thread = QThread()
        worker.moveToThread(self.engine_thread)
        self.engine_thread.started.connect(worker.run)
        worker.log.connect(self._log)
        worker.finished.connect(self._on_engine_finished)
        worker.finished.connect(self.engine_thread.quit)
        self.engine_thread.finished.connect(self._on_engine_thread_done)
        self.engine_thread.start()

    def _on_engine_finished(self, ok: bool, msg: str) -> None:
        self._log("INFO" if ok else "ERROR", msg)
        self._refresh_engine_status()

    def _on_engine_thread_done(self) -> None:
        if self.engine_thread is not None:
            self.engine_thread.deleteLater()
        self.engine_thread = None
        self.btn_engine.setEnabled(True)

    # ------------------------------------------------------------ 播放
    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_play_state(self, state) -> None:
        self.btn_play.setText("||" if state == QMediaPlayer.PlayingState else "▶")

    def _on_position(self, pos: int) -> None:
        if not self.pos_slider.isSliderDown():
            self.pos_slider.setValue(pos)
        self.time_label.setText(f"{fmt_ms(pos)} / {fmt_ms(self.player.duration())}")

    def _on_duration(self, dur: int) -> None:
        self.pos_slider.setRange(0, max(0, dur))
        self.pos_slider.setEnabled(dur > 0)
        self.time_label.setText(f"{fmt_ms(0)} / {fmt_ms(dur)}")

    def _seek(self, value: int) -> None:
        self.time_label.setText(f"{fmt_ms(value)} / {fmt_ms(self.player.duration())}")

    def _open_dir(self) -> None:
        if not self.current_result:
            return
        folder = os.path.dirname(self.current_result.wav_path)
        os.startfile(folder)  # noqa: S606 - Windows 资源管理器

    def _open_srt(self) -> None:
        if self.current_result:
            os.startfile(self.current_result.srt_path)  # noqa: S606

    # ------------------------------------------------------------ 日志
    def _log(self, level: str, message: str) -> None:
        color = {"ERROR": "#FF6B6B", "WARNING": "#F5C451", "INFO": "#9AA3B8"}.get(level, "#9AA3B8")
        stamp = time.strftime("%H:%M:%S")
        html = f'<span style="color:#5C6272">[{stamp}]</span> <span style="color:{color}">{escape(message)}</span>'
        self.log_view.appendHtml(html)
        self.log_view.moveCursor(QTextCursor.End)

    def closeEvent(self, event) -> None:
        self.cancel_evt.set()
        self.timer.stop()
        self.player.stop()
        self.manager.stop()
        self._collect_settings()
        super().closeEvent(event)


def escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))


def fmt_ms(ms: int) -> str:
    ms = max(0, int(ms))
    total = ms // 1000
    return f"{total // 60:02d}:{total % 60:02d}"
