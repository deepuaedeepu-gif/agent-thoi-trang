"""Kho dữ liệu cục bộ của app (thư mục `data/`, mỗi bản ghi là một file JSON).

data/
  formulas/<id>.json            công thức thành công (kèm nguồn, video đã phân tích)
  presenters/<id>/presenter.json  người dẫn (+ ảnh, video đồng ý nếu là người thật)
  voices/<id>/voice.json        giọng đọc (+ mp3 mẫu, bản ghi đồng ý nếu là giọng người thật)
  products/<id>/product.json    sản phẩm (+ ảnh)
  jobs/<id>/                    kết quả mỗi lần tạo kịch bản
"""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .models import AnalyzedVideo, ChannelFormula

DATA_DIR = Path("data")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.encode("ascii", "ignore").decode()).strip("-").lower()
    return f"{text or 'muc'}-{int(time.time() * 1000) % 10**8}"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- Bản ghi ----------

class SavedFormula(BaseModel):
    id: str
    name: str
    sources: list[str] = Field(description="Link kênh/video đã quét")
    created_at: str
    video_count: int
    formula: ChannelFormula
    videos: list[AnalyzedVideo] = []


class Consent(BaseModel):
    """Bằng chứng đồng ý của người thật. Bắt buộc với người dẫn/giọng là người thật."""

    person_name: str
    consent_video: str | None = None  # đường dẫn video tự quay nói câu đồng ý (người dẫn)
    consent_audio: str | None = None  # bản ghi câu đồng ý bằng chính giọng đó (voice)
    statement: str
    verified: bool = False
    verified_at: str | None = None


class Presenter(BaseModel):
    id: str
    name: str
    kind: Literal["ai_original", "real_person"]
    description_en: str = Field(description="Mô tả ngoại hình tiếng Anh, chép vào mọi prompt Veo")
    images: list[str] = []
    consent: Consent | None = None
    created_at: str

    @property
    def usable(self) -> bool:
        return self.kind == "ai_original" or bool(self.consent and self.consent.verified)

    def as_presenter_cfg(self) -> dict:
        """Chuyển về dạng `presenter.yaml` mà bộ viết kịch bản đang dùng."""
        if not self.usable:
            raise ValueError(f"Người dẫn '{self.name}' là người thật nhưng chưa xác minh đồng ý.")
        if self.kind == "ai_original":
            return {"mode": "ai_original", "ai_original": {"description_en": self.description_en}}
        return {"mode": "owner", "owner": {"verified": True, "description_en": self.description_en,
                                           "reference_images": self.images}}


class Voice(BaseModel):
    id: str
    name: str
    provider: str  # google_tts | fpt_ai | elevenlabs | custom
    provider_voice_id: str
    gender: str = ""
    region: str = ""
    kind: Literal["stock", "cloned"] = "stock"
    sample: str | None = None
    consent: Consent | None = None
    created_at: str = ""

    @property
    def usable(self) -> bool:
        return self.kind == "stock" or bool(self.consent and self.consent.verified)


class Product(BaseModel):
    id: str
    name: str
    price: str = ""
    details: str = ""
    selling_points: list[str] = []
    images: list[str] = []
    created_at: str = ""


# ---------- Lưu / đọc ----------

class Store:
    def __init__(self, root: Path | str = DATA_DIR):
        self.root = Path(root)
        for sub in ("formulas", "presenters", "voices", "products", "jobs"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self._seed()

    # Công thức
    def save_formula(self, f: SavedFormula) -> None:
        (self.root / "formulas" / f"{f.id}.json").write_text(f.model_dump_json(indent=2), encoding="utf-8")

    def formulas(self) -> list[SavedFormula]:
        return sorted((SavedFormula.model_validate_json(p.read_text(encoding="utf-8"))
                       for p in (self.root / "formulas").glob("*.json")), key=lambda f: f.created_at, reverse=True)

    def delete_formula(self, fid: str) -> None:
        (self.root / "formulas" / f"{fid}.json").unlink(missing_ok=True)

    # Người dẫn / voice / sản phẩm: mỗi bản ghi một thư mục để chứa file kèm theo
    def _dir(self, kind: str, rid: str) -> Path:
        d = self.root / kind / rid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_presenter(self, p: Presenter) -> None:
        (self._dir("presenters", p.id) / "presenter.json").write_text(p.model_dump_json(indent=2), encoding="utf-8")

    def presenters(self) -> list[Presenter]:
        return [Presenter.model_validate_json(p.read_text(encoding="utf-8"))
                for p in sorted((self.root / "presenters").glob("*/presenter.json"))]

    def save_voice(self, v: Voice) -> None:
        (self._dir("voices", v.id) / "voice.json").write_text(v.model_dump_json(indent=2), encoding="utf-8")

    def voices(self) -> list[Voice]:
        return [Voice.model_validate_json(p.read_text(encoding="utf-8"))
                for p in sorted((self.root / "voices").glob("*/voice.json"))]

    def save_product(self, p: Product) -> None:
        (self._dir("products", p.id) / "product.json").write_text(p.model_dump_json(indent=2), encoding="utf-8")

    def products(self) -> list[Product]:
        return sorted((Product.model_validate_json(p.read_text(encoding="utf-8"))
                       for p in (self.root / "products").glob("*/product.json")),
                      key=lambda p: p.created_at, reverse=True)

    def save_file(self, kind: str, rid: str, filename: str, data: bytes) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
        path = self._dir(kind, rid) / safe
        path.write_bytes(data)
        return str(path)

    def new_job_dir(self) -> Path:
        d = self.root / "jobs" / datetime.now().strftime("%Y%m%d-%H%M%S")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _seed(self) -> None:
        """Lần chạy đầu: tạo sẵn 1 người dẫn AI mẫu."""
        if not any((self.root / "presenters").glob("*/presenter.json")):
            self.save_presenter(Presenter(
                id="may-ai", name="Mây (nhân vật AI)", kind="ai_original", created_at=now(),
                description_en=(
                    "A fictional Vietnamese woman in her mid-20s, shoulder-length dark brown hair with soft "
                    "curtain bangs, warm friendly smile, natural makeup, slim build, confident and playful "
                    "energy. She is an original AI character and does not resemble any real person."),
            ))
        if not any((self.root / "voices").glob("*/voice.json")):
            # Giọng tiếng Việt có sẵn của Google Cloud TTS. Kho voice đầy đủ (FPT.AI, ElevenLabs) làm ở bước sau.
            for tier in ("Neural2", "Wavenet", "Standard"):
                letters = "AD" if tier == "Neural2" else "ABCD"
                for letter in letters:
                    gender = "Nữ" if letter in "AC" else "Nam"
                    vid = f"vi-VN-{tier}-{letter}"
                    self.save_voice(Voice(id=vid.lower(), name=f"Google {tier} {letter} ({gender})",
                                          provider="google_tts", provider_voice_id=vid, gender=gender,
                                          region="Chuẩn", created_at=now()))
