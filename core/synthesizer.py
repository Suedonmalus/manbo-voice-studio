"""合成流水线：文本 → 逐句合成 → 拼接 → WAV + SRT。"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field

import numpy as np

from core import audio
from core.config import Voice
from core.engine_client import EngineError, TTSClient
from core.segmenter import split_for_subtitle, split_sentences
from core.srt import write_srt


class SynthesisError(RuntimeError):
    pass


@dataclass
class SynthRequest:
    text: str
    voice: Voice
    output_dir: str
    basename: str = ""
    speed: float = 1.0
    gap_seconds: float = 0.25
    subtitle_max_chars: int = 16
    normalize: bool = True
    volume_db: float = 0.0
    max_sentence_len: int = 60


@dataclass
class SynthResult:
    wav_path: str
    srt_path: str
    duration: float
    sentence_count: int
    elapsed: float = 0.0


_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


def safe_basename(name: str, fallback: str = "曼波配音") -> str:
    name = _ILLEGAL.sub("_", (name or "").strip()).strip(" .")
    if not name:
        name = fallback
    return name[:60]


def unique_paths(out_dir: str, base: str) -> tuple[str, str]:
    wav = os.path.join(out_dir, base + ".wav")
    srt = os.path.join(out_dir, base + ".srt")
    i = 2
    while os.path.exists(wav) or os.path.exists(srt):
        wav = os.path.join(out_dir, f"{base}_{i}.wav")
        srt = os.path.join(out_dir, f"{base}_{i}.srt")
        i += 1
    return wav, srt


def auto_basename(text: str) -> str:
    head = re.sub(r"\s+", "", text.strip())[:18]
    return safe_basename(head)


def _subtitle_entries(sentences: list[str], spans: list[tuple[float, float]],
                      gap: float, max_chars: int) -> list[tuple[float, float, str]]:
    """把每句的时间区间展开成字幕行；超长句按字符数比例分配时间。"""
    entries: list[tuple[float, float, str]] = []
    n = len(sentences)
    for i, (sentence, (start, end)) in enumerate(zip(sentences, spans)):
        seg_end = end + (gap if i < n - 1 else 0.0)
        lines = split_for_subtitle(sentence, max_chars)
        if len(lines) == 1:
            entries.append((start, seg_end, lines[0]))
            continue
        total_chars = sum(len(x) for x in lines) or 1
        cursor = start
        span = max(seg_end - start, 0.01)
        for j, line in enumerate(lines):
            ratio = len(line) / total_chars
            line_end = seg_end if j == len(lines) - 1 else cursor + span * ratio
            entries.append((cursor, line_end, line))
            cursor = line_end
    return entries


def synthesize(req: SynthRequest, client: TTSClient, *, log_cb=None, progress_cb=None,
               cancel_cb=None) -> SynthResult:
    """执行一次完整合成。日志回调 (level, msg)，进度回调 (done, total, phase)。"""
    log = log_cb or (lambda *_: None)
    prog = progress_cb or (lambda *_: None)
    t_start = time.time()

    text = (req.text or "").strip()
    if not text:
        raise SynthesisError("文案为空，先输入要配音的文字。")

    sentences = split_sentences(text, max_len=max(10, req.max_sentence_len))
    if not sentences:
        raise SynthesisError("没有解析出可合成的句子。")
    total = len(sentences)
    log("INFO", f"文案切分为 {total} 句，共 {len(text)} 字")

    out_dir = req.output_dir or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    base = safe_basename(req.basename) if req.basename.strip() else auto_basename(text)
    wav_path, srt_path = unique_paths(out_dir, base)

    tmp_dir = tempfile.mkdtemp(prefix="manbo_synth_")
    segments: list[tuple[np.ndarray, int]] = []
    try:
        for i, sentence in enumerate(sentences, 1):
            if cancel_cb and cancel_cb():
                raise SynthesisError("已取消")
            prog(i - 1, total, f"正在合成第 {i}/{total} 句")
            seg_path = os.path.join(tmp_dir, f"seg_{i:04d}.wav")
            log("INFO", f"[{i}/{total}] {sentence}")

            attempt = 0
            while True:
                attempt += 1
                try:
                    client.synthesize(
                        sentence, seg_path,
                        refer_wav=req.voice.ref_wav, prompt_text=req.voice.ref_text,
                        speed=req.speed, cancel_cb=cancel_cb, log_cb=log,
                    )
                    break
                except EngineError as e:
                    if attempt >= 2 or (cancel_cb and cancel_cb()):
                        raise SynthesisError(f"第 {i} 句合成失败：{e}") from e
                    log("WARNING", f"第 {i} 句失败（{e}），重试一次…")
            segments.append(audio.read_wav(seg_path))
            prog(i, total, f"已完成 {i}/{total} 句")

        log("INFO", "正在拼接音频…")
        data, sr, spans = audio.concat(segments, gap_seconds=req.gap_seconds)
        if req.normalize:
            data = audio.peak_normalize(data, -1.0)
        data = audio.apply_gain(data, req.volume_db)
        audio.write_wav(wav_path, data, sr)

        entries = _subtitle_entries(sentences, spans, req.gap_seconds, req.subtitle_max_chars)
        write_srt(srt_path, entries)

        duration = data.size / float(sr)
        elapsed = time.time() - t_start
        log("INFO", f"完成：{os.path.basename(wav_path)}（{duration:.1f} 秒，{total} 句，"
                     f"耗时 {elapsed:.1f} 秒）")
        return SynthResult(wav_path=wav_path, srt_path=srt_path, duration=duration,
                           sentence_count=total, elapsed=elapsed)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
