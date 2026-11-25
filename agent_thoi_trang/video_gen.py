"""Tạo clip video qua API chính thức.

- Gemini Omni Flash (Google, qua Gemini API, thay cho Veo 3.1 preview đã ngừng 22/10/2026): GEMINI_API_KEY
- Grok Imagine (xAI): XAI_API_KEY

Google Flow và muse.ai không có API tạo video chính thức nên không có ở đây.
Mỗi lệnh luôn gửi kèm ảnh người dẫn và ảnh sản phẩm làm ảnh tham chiếu.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

PROVIDERS = {"omni": "Gemini Omni Flash (Google)", "grok": "Grok Imagine (xAI)"}


class VideoGenError(RuntimeError):
    pass


@dataclass
class ClipRequest:
    prompt: str
    presenter_images: list[str]
    product_images: list[str]
    duration_s: int = 8
    aspect_ratio: str = "9:16"
    resolution: str = "720p"


def build_prompt(req: ClipRequest, presenter_desc: str, ref_tag=lambda i: f"<IMAGE_REF_{i}>") -> str:
    """Ghép prompt cảnh với chỉ dẫn bắt buộc dùng đúng người dẫn và sản phẩm."""
    n_people = len(req.presenter_images)
    person_refs = " ".join(ref_tag(i) for i in range(n_people))
    product_refs = " ".join(ref_tag(n_people + i) for i in range(len(req.product_images)))
    rules = [
        f"The presenter MUST be exactly the person shown in {person_refs}: same face, hair, body and skin tone. "
        f"Presenter description: {presenter_desc}" if n_people else f"Presenter: {presenter_desc}",
        f"The garment/product MUST match {product_refs} exactly: same color, fabric, cut, pockets and details."
        if product_refs else "",
        "No one speaks; no dialogue or lip-sync (Vietnamese voice-over is added later). Light ambient sound only.",
        "No on-screen text, captions, logos or watermarks.",
        f"Vertical {req.aspect_ratio} video.",
    ]
    return req.prompt.strip() + "\n\n" + "\n".join(r for r in rules if r)


def _b64(path: str) -> tuple[str, str]:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return base64.b64encode(Path(path).read_bytes()).decode(), mime


def _key(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise VideoGenError(f"Chưa có khoá {name}. Nhập ở tab Cài đặt của app.")
    return value


def generate_omni(req: ClipRequest, presenter_desc: str, out_path: Path) -> Path:
    from google import genai

    client = genai.Client(api_key=_key("GEMINI_API_KEY"))
    parts = []
    for img in req.presenter_images + req.product_images:
        data, mime = _b64(img)
        parts.append({"type": "image", "data": data, "mime_type": mime})
    parts.append({"type": "text", "text": build_prompt(req, presenter_desc)})
    interaction = client.interactions.create(
        model="gemini-omni-1.1-flash", input=parts, store=False, background=False, stream=False,
        response_format={"type": "video", "aspect_ratio": req.aspect_ratio, "resolution": req.resolution,
                         "delivery": "uri"},
    )
    video = interaction.output_video
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if getattr(video, "data", None):
        out_path.write_bytes(base64.b64decode(video.data))
    elif getattr(video, "uri", None):
        for _ in range(120):
            f = client.files.get(name=video.uri)
            state = str(getattr(f, "state", ""))
            if "ACTIVE" in state:
                break
            if "FAILED" in state:
                raise VideoGenError("Gemini báo tạo video thất bại.")
            time.sleep(5)
        client.files.download(file=video.uri, destination=str(out_path))
    else:
        raise VideoGenError("Gemini không trả về video (có thể bị bộ lọc an toàn chặn).")
    return out_path


def generate_grok(req: ClipRequest, presenter_desc: str, out_path: Path,
                  model: str = "grok-imagine-video-1.5") -> Path:
    headers = {"Authorization": f"Bearer {_key('XAI_API_KEY')}", "Content-Type": "application/json"}
    refs = []
    for img in req.presenter_images + req.product_images:
        data, mime = _b64(img)
        refs.append({"url": f"data:{mime};base64,{data}"})
    body = {"model": model, "prompt": build_prompt(req, presenter_desc, ref_tag=lambda i: f"reference image {i + 1}"),
            "reference_images": refs, "duration": max(1, min(15, int(req.duration_s))),
            "aspect_ratio": req.aspect_ratio, "resolution": req.resolution}
    r = requests.post("https://api.x.ai/v1/videos/generations", headers=headers, json=body, timeout=120)
    if r.status_code >= 400:
        raise VideoGenError(f"xAI từ chối yêu cầu ({r.status_code}): {r.text[:300]}")
    request_id = r.json()["request_id"]
    for _ in range(240):
        time.sleep(5)
        s = requests.get(f"https://api.x.ai/v1/videos/{request_id}", headers=headers, timeout=60).json()
        status = s.get("status")
        if status == "done":
            url = (s.get("video") or {}).get("url")
            if not url:
                raise VideoGenError("xAI không trả link video (có thể bị kiểm duyệt).")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(requests.get(url, timeout=300).content)
            return out_path
        if status in ("failed", "expired"):
            raise VideoGenError(f"xAI: {status} {(s.get('error') or {}).get('message', '')}")
    raise VideoGenError("xAI quá 20 phút chưa xong.")


def generate_clip(provider: str, req: ClipRequest, presenter_desc: str, out_path: Path) -> Path:
    if provider == "omni":
        return generate_omni(req, presenter_desc, out_path)
    if provider == "grok":
        return generate_grok(req, presenter_desc, out_path)
    raise VideoGenError(f"Nền tảng không hỗ trợ: {provider}")
