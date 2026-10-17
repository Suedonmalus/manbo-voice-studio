"""GPT-SoVITS 本地 HTTP API 客户端。

引擎默认监听 127.0.0.1:9880，接口约定见 core/engine_manager.py 的启动参数：
    POST /  JSON: {text, text_language, refer_wav_path, prompt_text,
                   prompt_language, speed, cut_punc}  → audio/wav 字节流
    GET  /control → 任意 JSON（用于探活）
"""
from __future__ import annotations

import os
import time

import requests

NO_PROXY = {"http": None, "https": None}
CUT_PUNC = "，。？！；：、…,.;?!"


class EngineError(RuntimeError):
    pass


def _looks_like_wav(head: bytes) -> bool:
    if len(head) < 44 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return False
    pos, limit = 12, min(len(head), 8192)
    while pos + 8 <= limit:
        cid = head[pos:pos + 4]
        size = int.from_bytes(head[pos + 4:pos + 8], "little")
        if cid == b"data":
            return size > 0
        pos += 8 + size + (size & 1)
    return False


class TTSClient:
    def __init__(self, api_url: str = "http://127.0.0.1:9880"):
        self.api_url = api_url.rstrip("/")

    # ---------- 探活 ----------
    def is_online(self, timeout: float = 1.5) -> bool:
        try:
            r = requests.get(f"{self.api_url}/control", timeout=timeout, proxies=NO_PROXY)
            r.json()
            return True
        except Exception:
            return False

    # ---------- 合成 ----------
    def synthesize(self, text: str, out_path: str, *, refer_wav: str, prompt_text: str,
                   text_lang: str = "zh", prompt_lang: str = "zh", speed: float = 1.0,
                   cancel_cb=None, log_cb=None) -> None:
        """合成一段文本到 out_path（WAV）。失败抛 EngineError。"""
        log_cb = log_cb or (lambda *_: None)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

        lang = self._detect_lang(text, text_lang)
        params = {
            "text": text,
            "text_language": lang,
            "refer_wav_path": refer_wav,
            "prompt_text": prompt_text,
            "prompt_language": self._detect_lang(prompt_text, prompt_lang),
            "speed": max(0.1, min(3.0, float(speed))),
            "cut_punc": CUT_PUNC,
        }
        read_timeout = min(900.0, max(120.0, len(text) * 1.5))

        try:
            with requests.post(f"{self.api_url}/", json=params, stream=True,
                               timeout=(10, read_timeout), proxies=NO_PROXY) as r:
                if r.status_code != 200:
                    body = (r.text or "")[:300]
                    raise EngineError(f"引擎返回 {r.status_code}：{body}")
                tmp = out_path + ".part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 18):
                        if cancel_cb and cancel_cb():
                            break
                        if chunk:
                            f.write(chunk)
                if cancel_cb and cancel_cb():
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    raise EngineError("已取消")

                with open(tmp, "rb") as f:
                    head = f.read(8192)
                if not _looks_like_wav(head):
                    size = os.path.getsize(tmp)
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    raise EngineError(f"引擎返回的不是有效 WAV（{size} 字节），请查看引擎日志")

                os.replace(tmp, out_path)
        except EngineError:
            raise
        except requests.exceptions.Timeout as e:
            self._cleanup(out_path)
            raise EngineError(f"引擎响应超时（{int(read_timeout)} 秒）：{e}") from e
        except requests.exceptions.ConnectionError as e:
            self._cleanup(out_path)
            raise EngineError(f"无法连接引擎 {self.api_url}：{e}") from e
        except Exception as e:
            self._cleanup(out_path)
            raise EngineError(f"{type(e).__name__}: {e}") from e

    @staticmethod
    def _cleanup(path: str) -> None:
        for p in (path, path + ".part"):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    @staticmethod
    def _detect_lang(text: str, default: str) -> str:
        for ch in text or "":
            cp = ord(ch)
            if 0x3040 <= cp <= 0x30FF:   # 假名
                return "ja"
        return default


def wait_until_online(client: TTSClient, timeout: float = 60.0, cancel_cb=None) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_cb and cancel_cb():
            return False
        if client.is_online():
            return True
        time.sleep(0.5)
    return False
