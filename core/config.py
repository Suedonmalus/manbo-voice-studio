"""配置：音色、语速、输出、字幕等参数的持久化。"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")

# 模型目录（音色模型统一放这里，与引擎目录解耦）
MODELS_DIR = os.path.join(ROOT, "models")

# 引擎候选目录：GPT-SoVITS 对中文路径敏感，默认装到纯英文路径
_ENGINE_CANDIDATES = [
    r"F:\MamboVoiceEngine\GPT-SoVITS",
    r"D:\MamboVoiceEngine\GPT-SoVITS",
    os.path.join(ROOT, "engine", "GPT-SoVITS"),
]


def resolve_engine_dir() -> str:
    """确定引擎目录：配置优先，其次按候选顺序探测。"""
    override = ""
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                override = (json.load(f).get("engine_dir") or "").strip()
        except Exception:
            override = ""
    if override:
        return override
    for cand in _ENGINE_CANDIDATES:
        if os.path.isfile(os.path.join(cand, "api.py")):
            return cand
    return _ENGINE_CANDIDATES[0]


ENGINE_DIR = resolve_engine_dir()

DEFAULT_REF_TEXT = "大家好，欢迎来到我的频道，今天给大家分享一个有趣的内容"


@dataclass
class Voice:
    """一组可用的音色：SoVITS 模型 + GPT 模型 + 参考音频。"""
    name: str
    sovits: str
    gpt: str
    ref_wav: str
    ref_text: str = DEFAULT_REF_TEXT


@dataclass
class Settings:
    api_url: str = "http://127.0.0.1:9880"
    output_dir: str = ""
    voice: str = "曼波"
    speed: float = 1.0
    gap_seconds: float = 0.25
    subtitle_max_chars: int = 16
    normalize: bool = True
    volume_db: float = 0.0
    max_sentence_len: int = 60
    filename: str = ""
    dark_theme: bool = True
    auto_start_engine: bool = True

    # ---------- 持久化 ----------
    @classmethod
    def load(cls) -> "Settings":
        if not os.path.exists(CONFIG_PATH):
            return cls()
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except Exception:
            return cls()

    def save(self) -> None:
        # 保留文件里的额外字段（例如 installer 写入的 engine_dir），避免被 UI 配置覆盖
        data: dict = {}
        if os.path.isfile(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data.update(asdict(self))
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


def _ascii_voice_dir() -> str:
    """引擎侧的参考音频缓存目录（纯英文路径，规避 libsndfile 的中文路径问题）。"""
    return os.path.join(os.path.dirname(resolve_engine_dir()), "voices")


def ensure_ascii_ref(ref_wav: str) -> str:
    """参考音频若是中文路径，复制一份到英文路径并返回新路径。"""
    if not ref_wav or ref_wav.isascii():
        return ref_wav
    import shutil
    try:
        dest_dir = _ascii_voice_dir()
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(ref_wav))
        if not os.path.exists(dest) or os.path.getmtime(dest) < os.path.getmtime(ref_wav):
            shutil.copy2(ref_wav, dest)
        return dest
    except OSError:
        return ref_wav


def discover_voices() -> dict[str, Voice]:
    """扫描 models/ 下的音色模型，返回 {音色名: Voice}。

    约定命名：<音色名>_e<xx>_s<xxx>.pth（SoVITS）、<音色名>-e<xx>.ckpt（GPT）、
    <音色名>.wav 或 refer.wav（参考音频）。
    """
    voices: dict[str, Voice] = {}
    if not os.path.isdir(MODELS_DIR):
        return voices

    pth_files = [f for f in os.listdir(MODELS_DIR) if f.lower().endswith(".pth")]
    ckpt_files = [f for f in os.listdir(MODELS_DIR) if f.lower().endswith(".ckpt")]
    wav_files = [f for f in os.listdir(MODELS_DIR) if f.lower().endswith(".wav")]

    def key_of(name: str, model_name: str) -> str:
        stem = os.path.splitext(model_name)[0]
        return stem.split("_")[0].split("-")[0].lower()

    for pth in pth_files:
        key = key_of("", pth)
        ckpt = next((c for c in ckpt_files if key_of("", c) == key), None)
        if not ckpt:
            continue
        wav = next((w for w in wav_files if os.path.splitext(w)[0].lower() == key), None)
        if not wav:
            wav = next((w for w in wav_files if w.lower() == "refer.wav"), None)
        if not wav:
            continue
        display = "曼波" if key in ("manbo", "mambo", "refer") else os.path.splitext(wav)[0]
        voices[display] = Voice(
            name=display,
            sovits=os.path.join(MODELS_DIR, pth),
            gpt=os.path.join(MODELS_DIR, ckpt),
            ref_wav=os.path.join(MODELS_DIR, wav),
        )

    # 没有微调模型时，退化为「零样本」：用官方 v2Pro 预训练 + 参考音频直接克隆音色
    if not voices:
        ref = os.path.join(MODELS_DIR, "refer.wav")
        if os.path.isfile(ref):
            voices["曼波（零样本）"] = Voice(
                name="曼波（零样本）", sovits="", gpt="", ref_wav=ref,
            )

    # 参考音频统一换成英文路径，规避引擎侧的中文路径问题
    for v in voices.values():
        v.ref_wav = ensure_ascii_ref(v.ref_wav)
    return voices


def resolve_voice(name: str) -> Voice | None:
    voices = discover_voices()
    if not voices:
        return None
    if name in voices:
        return voices[name]
    return next(iter(voices.values()))
