"""界面主题（深色 / 浅色 QSS）。"""
from __future__ import annotations

DARK = """
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; }

QWidget {
    background-color: #14151A;
    color: #E8E9EE;
    font-size: 13px;
}
QMainWindow, #Root { background-color: #14151A; }

#Header {
    background-color: #1A1C23;
    border-bottom: 1px solid #262933;
}
#Title { font-size: 18px; font-weight: 600; color: #FFE9F0; }
#Subtitle { color: #8A8FA0; font-size: 12px; }

QGroupBox {
    background-color: #1A1C23;
    border: 1px solid #262933;
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
    color: #C9CDD8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #FF9BC0;
}

QPlainTextEdit, QLineEdit, QSpinBox, QComboBox {
    background-color: #101116;
    border: 1px solid #2A2E3A;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: #FF6FA5;
    selection-color: #14151A;
}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #FF6FA5;
}
QPlainTextEdit {
    font-size: 14px;
    line-height: 150%;
}

QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #1A1C23;
    border: 1px solid #2A2E3A;
    selection-background-color: #FF6FA5;
    selection-color: #14151A;
    outline: none;
}

QPushButton {
    background-color: #262A35;
    border: 1px solid #333846;
    border-radius: 8px;
    padding: 8px 16px;
    color: #E8E9EE;
}
QPushButton:hover { background-color: #2E3340; border-color: #3D4353; }
QPushButton:pressed { background-color: #22262F; }
QPushButton:disabled { color: #5C6272; background-color: #1C1F27; border-color: #262A33; }

QPushButton#Primary {
    background-color: #FF6FA5;
    border: none;
    color: #1A0C12;
    font-weight: 700;
    padding: 10px 26px;
    font-size: 14px;
}
QPushButton#Primary:hover { background-color: #FF85B4; }
QPushButton#Primary:pressed { background-color: #E85F92; }
QPushButton#Primary:disabled { background-color: #4A3440; color: #8A6E7A; }

QPushButton#Ghost {
    background-color: transparent;
    border: 1px solid #333846;
}

QSlider::groove:horizontal {
    height: 5px;
    background: #262A35;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #FF6FA5;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #FFE9F0;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: #FFFFFF; }

QProgressBar {
    background-color: #1C1F27;
    border: 1px solid #2A2E3A;
    border-radius: 8px;
    height: 16px;
    text-align: center;
    color: #E8E9EE;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: #FF6FA5;
    border-radius: 7px;
}

QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid #3D4353;
    background: #101116;
}
QCheckBox::indicator:checked {
    background: #FF6FA5;
    border-color: #FF6FA5;
}

QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: #333846; border-radius: 5px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: #414859; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #333846; border-radius: 5px; min-width: 28px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

#LogView {
    background-color: #0E0F13;
    border: 1px solid #22252E;
    border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
    color: #A8AEBF;
}

#StatusDot { font-size: 15px; }
#Hint { color: #7C8296; font-size: 12px; }
#ValueLabel { color: #FFB3CE; font-weight: 600; min-width: 52px; }
#Meta { color: #8A8FA0; font-size: 12px; }
QToolTip {
    background-color: #1A1C23;
    color: #E8E9EE;
    border: 1px solid #333846;
    padding: 5px;
}
"""

LIGHT = """
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; }

QWidget { background-color: #F7F8FA; color: #1E2028; font-size: 13px; }
QMainWindow, #Root { background-color: #F7F8FA; }

#Header { background-color: #FFFFFF; border-bottom: 1px solid #E4E7EE; }
#Title { font-size: 18px; font-weight: 600; color: #D6336C; }
#Subtitle { color: #7C8394; font-size: 12px; }

QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #E4E7EE;
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
    color: #3C4252;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #E0426F;
}

QPlainTextEdit, QLineEdit, QSpinBox, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #DDE1EA;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: #FF8CB5;
    selection-color: #FFFFFF;
}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #FF6FA5;
}
QPlainTextEdit { font-size: 14px; line-height: 150%; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #FFFFFF; border: 1px solid #DDE1EA;
    selection-background-color: #FF6FA5; selection-color: #FFFFFF; outline: none;
}

QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #DDE1EA;
    border-radius: 8px;
    padding: 8px 16px;
    color: #2A2F3C;
}
QPushButton:hover { background-color: #F3F5F9; border-color: #C9D0DE; }
QPushButton:disabled { color: #A9B0BE; background-color: #F2F4F7; }

QPushButton#Primary {
    background-color: #FF6FA5; border: none; color: #FFFFFF;
    font-weight: 700; padding: 10px 26px; font-size: 14px;
}
QPushButton#Primary:hover { background-color: #FF85B4; }
QPushButton#Primary:disabled { background-color: #FFD3E2; color: #FFFFFF; }
QPushButton#Ghost { background-color: transparent; border: 1px solid #DDE1EA; }

QSlider::groove:horizontal { height: 5px; background: #E4E7EE; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #FF6FA5; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #FFFFFF; border: 2px solid #FF6FA5; width: 12px; height: 12px;
    margin: -6px 0; border-radius: 7px;
}

QProgressBar {
    background-color: #EEF1F6; border: 1px solid #E0E4EC; border-radius: 8px;
    height: 16px; text-align: center; color: #3C4252; font-size: 11px;
}
QProgressBar::chunk { background-color: #FF6FA5; border-radius: 7px; }

QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #C9D0DE; background: #FFFFFF;
}
QCheckBox::indicator:checked { background: #FF6FA5; border-color: #FF6FA5; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #D4D9E3; border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

#LogView {
    background-color: #FBFCFE; border: 1px solid #E4E7EE; border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; color: #5A6070;
}
#Hint { color: #7C8394; font-size: 12px; }
#ValueLabel { color: #D6336C; font-weight: 600; min-width: 52px; }
#Meta { color: #7C8394; font-size: 12px; }
"""


def stylesheet(dark: bool) -> str:
    return DARK if dark else LIGHT
