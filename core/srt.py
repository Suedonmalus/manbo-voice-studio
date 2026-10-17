"""SRT 字幕生成。"""
from __future__ import annotations


def format_ts(seconds: float) -> str:
    """秒 → SRT 时间戳 HH:MM:SS,mmm。"""
    if seconds < 0:
        seconds = 0.0
    ms_total = int(round(seconds * 1000.0))
    h, ms_total = divmod(ms_total, 3600_000)
    m, ms_total = divmod(ms_total, 60_000)
    s, ms = divmod(ms_total, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(entries: list[tuple[float, float, str]]) -> str:
    """entries: [(start_sec, end_sec, text), ...] → srt 文本。"""
    lines: list[str] = []
    seq = 1
    for start, end, text in entries:
        if end <= start:
            end = start + 0.2
        lines.append(str(seq))
        lines.append(f"{format_ts(start)} --> {format_ts(end)}")
        lines.append(text)
        lines.append("")
        seq += 1
    return "\n".join(lines)


def write_srt(path: str, entries: list[tuple[float, float, str]]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write(build_srt(entries))
