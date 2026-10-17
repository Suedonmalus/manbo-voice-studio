"""文本切分：把整段文案切成适合 TTS 合成的句子。

切分原则：
1. 优先按换行切段；
2. 段内按句末标点（。！？；…）切句，并保留标点；
3. 过长的句子再按逗号类软标点切，仍超长则按字数硬切，避免单次合成爆长度上限；
4. 不丢失任何可见字符（拼接回去应与原文等价，只差空白）。
"""
from __future__ import annotations

import re

HARD_END = "。！？!?…；;～~"
SOFT_END = "，,、：:—"
CLOSERS = "”’\"'）)】》」』…"

# 一句 = 非句末字符 + 任意个句末字符 + 任意个收尾符号
_SENT_RE = re.compile(rf"[^{re.escape(HARD_END)}\n]+[{re.escape(HARD_END)}]*[{re.escape(CLOSERS)}]*")
_SOFT_RE = re.compile(rf"[^{re.escape(SOFT_END)}]+[{re.escape(SOFT_END)}]*")


def _split_long(sentence: str, max_len: int) -> list[str]:
    """把超长句按软标点切成不超过 max_len 的块。"""
    if len(sentence) <= max_len:
        return [sentence]

    pieces: list[str] = []
    buf = ""
    for piece in _SOFT_RE.findall(sentence) or [sentence]:
        if len(buf) + len(piece) <= max_len:
            buf += piece
            continue
        if buf.strip():
            pieces.append(buf)
            buf = ""
        # 单块仍超长：按字数硬切
        while len(piece) > max_len:
            pieces.append(piece[:max_len])
            piece = piece[max_len:]
        buf = piece
    if buf.strip():
        pieces.append(buf)

    # 合并过碎的碎片（比如 "……" 单独成块）
    merged: list[str] = []
    for p in pieces:
        if merged and len(merged[-1]) + len(p) <= max_len:
            merged[-1] += p
        else:
            merged.append(p)
    return [p for p in merged if p.strip()]


def split_sentences(text: str, max_len: int = 45) -> list[str]:
    """把文案切成句子列表。"""
    if not text:
        return []

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u3000]+", " ", text)

    sentences: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for raw in _SENT_RE.findall(line):
            s = raw.strip()
            if not s:
                continue
            sentences.extend(_split_long(s, max_len))

    # 纯标点碎片（如单独的「……」）并入前一句，避免合成出无意义的短句
    final: list[str] = []
    for s in sentences:
        if final and not _has_word(s):
            final[-1] += s
        else:
            final.append(s)
    return final


def _has_word(text: str) -> bool:
    """是否含有实际文字（汉字/字母/数字），用于识别纯标点碎片。"""
    for ch in text:
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def split_for_subtitle(sentence: str, max_chars: int) -> list[str]:
    """把一句字幕再按字数/标点切成多行，供 srt 使用。

    关键约束：标点不能单独成行（字幕里孤零零一个「。」很丑），
    因此纯标点碎片一律并入前一行。
    """
    if max_chars <= 0 or len(sentence) <= max_chars:
        return [sentence]

    # 1) 按软标点聚合到不超过 max_chars 的块
    chunks: list[str] = []
    buf = ""
    for piece in _SOFT_RE.findall(sentence) or [sentence]:
        if len(buf) + len(piece) <= max_chars:
            buf += piece
            continue
        if buf:
            chunks.append(buf)
        buf = piece
    if buf:
        chunks.append(buf)

    # 2) 仍然超长的块硬切，优先在软标点之后断开
    out: list[str] = []
    for c in chunks:
        while len(c) > max_chars:
            cut = max_chars
            for k in range(max_chars, max(1, max_chars - 6), -1):
                if k - 1 < len(c) and c[k - 1] in SOFT_END:
                    cut = k
                    break
            out.append(c[:cut])
            c = c[cut:]
        if c:
            out.append(c)

    # 3) 纯标点碎片并入前一块
    merged: list[str] = []
    for c in out:
        if merged and not _has_word(c):
            merged[-1] += c
        else:
            merged.append(c)
    return [m.strip() for m in merged if m.strip()]
