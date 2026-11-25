"""Lớp gọi Claude duy nhất trong dự án: structured output + fallback khi bị từ chối."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from .config import MODEL

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    def parse(self, system: str, content: list[dict], schema: type[T], effort: str = "high") -> T: ...


class RefusalError(RuntimeError):
    pass


class ClaudeLLM:
    """Gọi Claude Opus 5.5 qua Messages API, trả về đối tượng Pydantic đã được kiểm tra."""

    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def parse(self, system: str, content: list[dict], schema: type[T], effort: str = "high") -> T:
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=64000,
            system=system,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            output_format=schema,
            # Nếu bộ lọc an toàn từ chối nhầm, API tự chạy lại trên model dự phòng.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            raise RefusalError(f"Claude từ chối yêu cầu: {message.stop_details}")
        if message.stop_reason == "max_tokens":
            raise RuntimeError("Kết quả bị cắt vì vượt max_tokens; hãy giảm số kịch bản mỗi lượt.")
        parsed = message.parsed_output
        if parsed is None:
            raise RuntimeError("Không đọc được kết quả có cấu trúc từ Claude.")
        return parsed


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


def image_block(path: str | Path) -> dict:
    path = Path(path)
    media_type = IMAGE_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"Định dạng ảnh không hỗ trợ: {path.name} (dùng jpg, png, webp)")
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
