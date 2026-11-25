"""Khoá API: lưu trên máy người dùng (data/settings.json) và nạp vào biến môi trường khi app chạy."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SETTINGS_FILE = Path("data/settings.json")


@dataclass(frozen=True)
class KeySpec:
    env: str
    label: str
    used_for: str
    required: bool
    guide: str


KEYS: list[KeySpec] = [
    KeySpec("ANTHROPIC_API_KEY", "Claude (Anthropic)", "Chỉ cần khi chọn kết nối Claude bằng khoá API thay cho Claude Code", False, """
1. Mở [platform.claude.com](https://platform.claude.com) (trước đây là console.anthropic.com) và đăng ký / đăng nhập.
2. Vào **Settings → Billing**, nạp tiền (tối thiểu khoảng 5 USD) để dùng API.
3. Vào **Settings → API Keys**, bấm **Create Key**, đặt tên (ví dụ `agent-thoi-trang`).
4. Sao chép khoá (bắt đầu bằng `sk-ant-`) và dán vào ô bên dưới. Khoá chỉ hiện một lần.
"""),
    KeySpec("GEMINI_API_KEY", "Gemini API (Google)", "Tạo video bằng Gemini Omni Flash", False, """
1. Mở [aistudio.google.com/apikey](https://aistudio.google.com/apikey) và đăng nhập tài khoản Google.
2. Bấm **Create API key**, chọn hoặc tạo một dự án Google Cloud.
3. Tạo video cần gói trả phí: bấm **Set up billing** cạnh khoá vừa tạo và gắn thẻ thanh toán.
4. Sao chép khoá (bắt đầu bằng `AIza`) và dán vào ô bên dưới.
"""),
    KeySpec("XAI_API_KEY", "xAI (Grok Imagine)", "Tạo video bằng Grok Imagine", False, """
1. Mở [console.x.ai](https://console.x.ai) và đăng ký / đăng nhập.
2. Vào **Billing**, nạp tín dụng.
3. Vào **API Keys**, bấm **Create API Key**, cho phép dùng các model video.
4. Sao chép khoá (bắt đầu bằng `xai-`) và dán vào ô bên dưới.
"""),
    KeySpec("GOOGLE_TTS_API_KEY", "Google Cloud Text-to-Speech", "Giọng đọc tiếng Việt của Google", False, """
1. Mở [console.cloud.google.com](https://console.cloud.google.com), tạo hoặc chọn một dự án, bật thanh toán (có hạn mức miễn phí hằng tháng).
2. Vào [trang Text-to-Speech API](https://console.cloud.google.com/apis/library/texttospeech.googleapis.com) và bấm **Enable**.
3. Vào **APIs & Services → Credentials → Create credentials → API key**.
4. Bấm vào khoá vừa tạo, mục **API restrictions** chọn **Cloud Text-to-Speech API** rồi **Save**.
5. Sao chép khoá và dán vào ô bên dưới. Có thể dùng chung dự án với Gemini nhưng nên tạo khoá riêng.
"""),
    KeySpec("FPT_AI_API_KEY", "FPT.AI Text-to-Speech", "Giọng đọc tiếng Việt của FPT (Ban Mai, Lê Minh, Lan Nhi...)", False, """
1. Mở [console.fpt.ai](https://console.fpt.ai) và đăng ký tài khoản.
2. Tạo một dự án (project) mới.
3. Trong dự án, mở mục **API Key** (hoặc **Credentials**) để xem khoá.
4. Sao chép khoá và dán vào ô bên dưới. Tài khoản mới thường có hạn mức dùng thử.
"""),
    KeySpec("ELEVENLABS_API_KEY", "ElevenLabs", "Giọng đọc ElevenLabs và tạo giọng mới từ file ghi âm", False, """
1. Mở [elevenlabs.io](https://elevenlabs.io) và đăng ký / đăng nhập.
2. Tạo giọng mới từ ghi âm (Instant Voice Cloning) cần gói **Starter** trở lên.
3. Vào [Settings → API Keys](https://elevenlabs.io/app/settings/api-keys), bấm **Create API Key**, bật quyền Text to Speech và Voices.
4. Sao chép khoá và dán vào ô bên dưới.
"""),
]


CLAUDE_CODE_GUIDE = """
1. Cần gói **Claude Pro** hoặc **Max** (đăng ký tại [claude.ai](https://claude.ai)).
2. Cài Claude Code theo [hướng dẫn chính thức](https://code.claude.com/docs/en/setup):
   - **macOS / Linux:** mở Terminal, chạy `curl -fsSL https://claude.ai/install.sh | bash`
   - **Windows:** mở PowerShell, chạy `irm https://claude.ai/install.ps1 | iex`
3. Mở Terminal / PowerShell mới, gõ `claude`, chọn đăng nhập bằng **tài khoản Claude (Pro/Max)** và làm theo trình duyệt.
4. Gõ `/exit` để thoát, đóng rồi mở lại app này, bấm **Kiểm tra kết nối**.

Lưu ý: mỗi lần viết/chấm kịch bản dùng lượt của gói. Gói có giới hạn theo khung giờ; nếu chạm giới hạn, chờ
hoặc giảm số kịch bản. Cách này chỉ dành cho chính bạn dùng trên máy của mình, không chia sẻ app kèm tài khoản.
"""


def load(path: Path = SETTINGS_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if isinstance(v, str)}
    except (json.JSONDecodeError, OSError):
        return {}


def save(values: dict[str, str], path: Path = SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v.strip() for k, v in values.items() if v and v.strip()}
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    apply(clean, override=True)


def apply(values: dict[str, str] | None = None, override: bool = False) -> None:
    """Nạp khoá đã lưu vào biến môi trường. Biến môi trường đặt sẵn được ưu tiên, trừ khi override."""
    for k, v in (load() if values is None else values).items():
        if override or not os.environ.get(k):
            os.environ[k] = v
    if override and values is not None:
        for spec in KEYS:
            if spec.env not in values and spec.env != "LLM_BACKEND":
                os.environ.pop(spec.env, None)


def mask(value: str) -> str:
    return f"{value[:6]}…{value[-4:]}" if len(value) > 12 else "đã nhập"
