"""Lớp gọi Claude duy nhất trong dự án: structured output + fallback khi bị từ chối."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
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


class ClaudeCodeLLM:
    """Gọi Claude Code đã cài và đăng nhập trên máy (dùng gói Pro/Max của chính người dùng).

    Chạy `claude -p` ở chế độ không tương tác, không bật công cụ nào, ép kết quả theo JSON Schema.
    Chỉ dành cho chính chủ tài khoản dùng trên máy của mình.
    """

    def __init__(self, model: str = "opus", timeout: int = 900, executable: str | None = None):
        self.model = model
        self.timeout = timeout
        self.executable = executable or claude_code_path()
        if not self.executable:
            raise RuntimeError("Không tìm thấy Claude Code. Cài theo hướng dẫn ở tab Cài đặt rồi mở lại app.")

    def command(self, system: str, schema_json: str) -> list[str]:
        return [self.executable, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose", "--json-schema", schema_json, "--tools", "", "--system-prompt", system,
                "--model", self.model, "--no-session-persistence", "--strict-mcp-config"]

    def parse(self, system: str, content: list[dict], schema: type[T], effort: str = "high") -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        stdin = json.dumps({"type": "user", "message": {"role": "user", "content": content}}, ensure_ascii=False)
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # dùng phiên đăng nhập gói, không dùng khoá API
        proc = subprocess.run(self.command(system, schema_json), input=stdin, capture_output=True, text=True,
                              encoding="utf-8", timeout=self.timeout, env=env)
        return self.read_result(proc.stdout, proc.stderr, schema)

    @staticmethod
    def read_result(stdout: str, stderr: str, schema: type[T]) -> T:
        result = None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                result = event
        if result is None:
            raise RuntimeError(f"Claude Code không trả kết quả. {stderr.strip()[:300]}")
        if result.get("is_error"):
            raise RuntimeError(f"Claude Code báo lỗi: {result.get('result')} "
                               "(kiểm tra đã đăng nhập bằng lệnh `claude` và còn lượt dùng trong gói).")
        data = result.get("structured_output")
        if data is None:
            text = (result.get("result") or "").strip().removeprefix("```json").removesuffix("```")
            data = json.loads(text)
        return schema.model_validate(data)


def claude_code_path() -> str | None:
    return shutil.which("claude")


def make_llm() -> LLM:
    """Chọn nơi gọi Claude theo cài đặt LLM_BACKEND: 'claude_code' (mặc định) hoặc 'api'."""
    if os.environ.get("LLM_BACKEND", "claude_code") == "api":
        return ClaudeLLM()
    return ClaudeCodeLLM()


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
