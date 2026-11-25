"""Giọng đọc tiếng Việt qua API chính thức: Google Cloud TTS, FPT.AI, ElevenLabs.

Khoá API đọc từ biến môi trường:
  GOOGLE_TTS_API_KEY, FPT_AI_API_KEY, ELEVENLABS_API_KEY
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import requests

from .store import Voice, now

TIMEOUT = 60
ELEVEN_MODEL = "eleven_multilingual_v2"

FPT_VOICES = [  # theo docs.fpt.ai/docs/en/speech/api/text-to-speech
    ("banmai", "Ban Mai", "Nữ", "Bắc"), ("thuminh", "Thu Minh", "Nữ", "Bắc"), ("leminh", "Lê Minh", "Nam", "Bắc"),
    ("myan", "Mỹ An", "Nữ", "Trung"), ("giahuy", "Gia Huy", "Nam", "Trung"),
    ("lannhi", "Lan Nhi", "Nữ", "Nam"), ("linhsan", "Linh San", "Nữ", "Nam"),
]


class TTSError(RuntimeError):
    pass


def _key(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise TTSError(f"Chưa có khoá {name}. Nhập ở tab Cài đặt của app.")
    return value


# ---------- Danh sách giọng ----------

def fpt_stock_voices() -> list[Voice]:
    return [Voice(id=f"fpt-{vid}", name=f"FPT {name} ({gender}, {region})", provider="fpt_ai",
                  provider_voice_id=vid, gender=gender, region=region, created_at=now())
            for vid, name, gender, region in FPT_VOICES]


def google_voices() -> list[Voice]:
    r = requests.get("https://texttospeech.googleapis.com/v1/voices",
                     params={"languageCode": "vi-VN", "key": _key("GOOGLE_TTS_API_KEY")}, timeout=TIMEOUT)
    r.raise_for_status()
    voices = []
    for v in r.json().get("voices", []):
        gender = {"FEMALE": "Nữ", "MALE": "Nam"}.get(v.get("ssmlGender"), "")
        voices.append(Voice(id=v["name"].lower(), name=f"Google {v['name'].removeprefix('vi-VN-')} ({gender})",
                            provider="google_tts", provider_voice_id=v["name"], gender=gender, created_at=now()))
    return voices


def elevenlabs_voices() -> list[Voice]:
    r = requests.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": _key("ELEVENLABS_API_KEY")},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return [Voice(id=f"el-{v['voice_id']}", name=f"ElevenLabs {v['name']}", provider="elevenlabs",
                  provider_voice_id=v["voice_id"], gender=(v.get("labels") or {}).get("gender", ""), created_at=now())
            for v in r.json().get("voices", []) if v.get("category") != "cloned"]


# ---------- Tổng hợp giọng ----------

def synthesize(voice: Voice, text: str, out_path: Path) -> Path:
    if not voice.usable:
        raise TTSError(f"Giọng '{voice.name}' là giọng người thật chưa xác minh đồng ý.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if voice.provider == "google_tts":
        r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                          params={"key": _key("GOOGLE_TTS_API_KEY")}, timeout=TIMEOUT, json={
                              "input": {"text": text},
                              "voice": {"languageCode": "vi-VN", "name": voice.provider_voice_id},
                              "audioConfig": {"audioEncoding": "MP3"}})
        r.raise_for_status()
        out_path.write_bytes(base64.b64decode(r.json()["audioContent"]))
    elif voice.provider == "fpt_ai":
        r = requests.post("https://api.fpt.ai/hmi/tts/v5", data=text.encode("utf-8"), timeout=TIMEOUT,
                          headers={"api_key": _key("FPT_AI_API_KEY"), "voice": voice.provider_voice_id,
                                   "speed": "0", "format": "mp3"})
        r.raise_for_status()
        body = r.json()
        if body.get("error") != 0:
            raise TTSError(f"FPT.AI lỗi: {body.get('message')}")
        out_path.write_bytes(_poll_download(body["async"]))
    elif voice.provider == "elevenlabs":
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice.provider_voice_id}",
                          headers={"xi-api-key": _key("ELEVENLABS_API_KEY"), "accept": "audio/mpeg"},
                          json={"text": text, "model_id": ELEVEN_MODEL}, timeout=TIMEOUT)
        r.raise_for_status()
        out_path.write_bytes(r.content)
    else:
        raise TTSError(f"Nhà cung cấp chưa hỗ trợ: {voice.provider}")
    return out_path


def _poll_download(url: str, tries: int = 40, wait: float = 3.0) -> bytes:
    """FPT.AI trả link trước, file âm thanh có sau vài giây tới 2 phút."""
    for _ in range(tries):
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code == 200 and r.content:
            return r.content
        time.sleep(wait)
    raise TTSError("FPT.AI chưa trả file âm thanh sau 2 phút.")


# ---------- Tạo giọng mới (chỉ sau khi đã xác minh đồng ý) ----------

def clone_elevenlabs(voice: Voice, sample: Path) -> str:
    """Instant Voice Cloning của ElevenLabs. Mẫu giọng chính là file ghi âm đồng ý."""
    if not (voice.consent and voice.consent.verified):
        raise TTSError("Chỉ tạo giọng sau khi bản ghi đồng ý đã được xác minh.")
    with open(sample, "rb") as f:
        r = requests.post("https://api.elevenlabs.io/v1/voices/add", headers={"xi-api-key": _key("ELEVENLABS_API_KEY")},
                          data={"name": voice.name,
                                "description": f"Giọng của {voice.consent.person_name}, có xác minh đồng ý"},
                          files=[("files", (sample.name, f, "audio/mpeg"))], timeout=TIMEOUT * 2)
    r.raise_for_status()
    return r.json()["voice_id"]
