"""WAV 音频工具：读取、重采样、拼接、归一化、写盘。

只依赖标准库 wave 与 numpy，避免引入 ffmpeg / pydub 这类外部依赖。
"""
from __future__ import annotations

import os
import wave

import numpy as np


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """读取 WAV，返回 (float32 单声道 [-1,1] 采样, 采样率)。"""
    with wave.open(path, "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sw == 1:  # 8bit 无符号
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (b[:, 0].astype(np.int32)
                | (b[:, 1].astype(np.int32) << 8)
                | (b[:, 2].astype(np.int32) << 16))
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        data = ints.astype(np.float32) / 8388608.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"不支持的位深：{sw * 8} bit")

    if nch > 1:
        data = data.reshape(-1, nch).mean(axis=1)
    return data.astype(np.float32), sr


def resample(data: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """线性插值重采样（够用且不引入额外依赖）。"""
    if src_sr == dst_sr or data.size == 0:
        return data
    n_out = int(round(data.size * dst_sr / src_sr))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.arange(data.size, dtype=np.float64)
    x_new = np.linspace(0, data.size, n_out, endpoint=False, dtype=np.float64)
    return np.interp(x_new, x_old, data).astype(np.float32)


def concat(segments: list[tuple[np.ndarray, int]], gap_seconds: float,
           target_sr: int | None = None) -> tuple[np.ndarray, int, list[tuple[float, float]]]:
    """拼接连结多段音频，段间插入静音。

    返回 (拼接后采样, 采样率, 每段在总轨上的 [开始, 结束] 时间戳)。
    时间戳不含段前静音，便于直接作为字幕起止时间。
    """
    if not segments:
        return np.zeros(0, dtype=np.float32), target_sr or 32000, []

    sr = target_sr or segments[0][1]
    gap = np.zeros(int(round(max(gap_seconds, 0.0) * sr)), dtype=np.float32)

    pieces: list[np.ndarray] = []
    spans: list[tuple[float, float]] = []
    cursor = 0  # 采样点位置
    for i, (data, seg_sr) in enumerate(segments):
        if i > 0 and gap.size:
            pieces.append(gap)
            cursor += gap.size
        data = resample(data, seg_sr, sr)
        start = cursor
        cursor += data.size
        pieces.append(data)
        spans.append((start / sr, cursor / sr))

    return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32), sr, spans


def peak_normalize(data: np.ndarray, target_db: float = -1.0) -> np.ndarray:
    """峰值归一化到 target_db（-1 dBFS 约 0.891）。"""
    if data.size == 0:
        return data
    peak = float(np.max(np.abs(data)))
    if peak < 1e-6:
        return data
    target = 10 ** (target_db / 20.0)
    return (data * (target / peak)).astype(np.float32)


def apply_gain(data: np.ndarray, db: float) -> np.ndarray:
    if abs(db) < 1e-6:
        return data
    return (data * (10 ** (db / 20.0))).astype(np.float32)


def write_wav(path: str, data: np.ndarray, sr: int) -> None:
    """写 16bit 单声道 PCM WAV。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    pcm = np.clip(data * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())


def duration_of(path: str) -> float:
    with wave.open(path, "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())
