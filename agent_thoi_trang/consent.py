"""Xác minh đồng ý cho khuôn mặt / giọng nói của người thật.

Cách làm:
1. App tạo một câu đồng ý có tên người, ngày hôm nay và MÃ NGẪU NHIÊN 4 chữ số (mã mới mỗi lần).
2. Người đó tự quay video (người dẫn) hoặc tự ghi âm (voice) đọc đúng câu này.
3. App chép lời file đó và so với câu mong đợi: phải có mã, tên và ý đồng ý.
4. Với người dẫn, ảnh tham chiếu được lấy TỪ CHÍNH video đồng ý (không nhận ảnh từ nguồn khác),
   để không thể ghép video đồng ý của người này với ảnh của người khác.
   Với voice, chính file ghi âm đồng ý là mẫu giọng để tạo voice.

Mã ngẫu nhiên khiến video/âm thanh tải từ mạng về không thể dùng để qua bước này.
"""

from __future__ import annotations

import difflib
import re
import secrets
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DIGIT_WORDS = {
    "không": "0", "một": "1", "mốt": "1", "hai": "2", "ba": "3", "bốn": "4", "tư": "4", "năm": "5",
    "lăm": "5", "sáu": "6", "bảy": "7", "bẩy": "7", "tám": "8", "chín": "9",
}


@dataclass
class Challenge:
    person_name: str
    code: str
    day: date
    purpose: str  # "khuôn mặt và giọng nói" | "giọng nói"

    @property
    def statement(self) -> str:
        return (f"Tôi là {self.person_name}. Hôm nay là ngày {self.day.day} tháng {self.day.month} năm {self.day.year}. "
                f"Mã xác nhận của tôi là {' '.join(self.code)}. "
                f"Tôi đồng ý cho agent video thời trang sử dụng {self.purpose} của tôi.")


SAMPLE_PARAGRAPH = (
    "Mùa này mình mê nhất là quần jeans ống loe lưng cao, mặc vào chân dài hẳn ra. Phối với áo thun trắng "
    "và giày thể thao là đi chơi cả ngày vẫn thoải mái. Nếu thích nữ tính hơn thì thử áo sơ mi lụa và "
    "túi nhỏ màu kem nhé. Mấy bà nhớ để lại bình luận chiều cao cân nặng để mình tư vấn size cho chuẩn."
)


def new_challenge(person_name: str, purpose: str, today: date | None = None) -> Challenge:
    return Challenge(person_name=person_name.strip(), code=f"{secrets.randbelow(10000):04d}",
                     day=today or date.today(), purpose=purpose)


def _plain(text: str) -> str:
    text = text.lower().replace("đ", "d")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def digits_in(text: str) -> str:
    """Lấy chuỗi chữ số theo thứ tự, hiểu cả số đọc bằng chữ ('bốn hai không bảy')."""
    out = []
    for token in re.findall(r"\w+", text.lower()):
        if token.isdigit():
            out.append(token)
        elif token in DIGIT_WORDS:
            out.append(DIGIT_WORDS[token])
    return "".join(out)


@dataclass
class VerifyResult:
    passed: bool
    transcript: str
    similarity: float
    code_found: bool
    name_found: bool
    consent_found: bool

    @property
    def reasons(self) -> list[str]:
        r = []
        if not self.code_found:
            r.append("không nghe thấy đúng mã xác nhận")
        if not self.name_found:
            r.append("không nghe thấy tên")
        if not self.consent_found:
            r.append("không nghe thấy câu đồng ý")
        if self.similarity < MIN_SIMILARITY:
            r.append(f"nội dung khác câu mẫu quá nhiều ({self.similarity:.0%})")
        return r


MIN_SIMILARITY = 0.6


def check_transcript(transcript: str, challenge: Challenge) -> VerifyResult:
    plain = _plain(transcript)
    expected = _plain(challenge.statement)
    # Câu đồng ý đọc đầu tiên; phần đọc thêm sau đó (mẫu giọng) không làm giảm điểm giống.
    similarity = difflib.SequenceMatcher(None, plain[: int(len(expected) * 1.3)], expected).ratio()
    name_tokens = _plain(challenge.person_name).split()
    name_found = all(t in plain.split() for t in name_tokens)
    code_found = challenge.code in digits_in(transcript)
    consent_found = "dong y" in plain
    return VerifyResult(
        passed=code_found and name_found and consent_found and similarity >= MIN_SIMILARITY,
        transcript=transcript, similarity=round(similarity, 3),
        code_found=code_found, name_found=name_found, consent_found=consent_found,
    )


def transcribe_plain(path: Path, model_size: str = "small") -> str:
    """Chép lời tiếng Việt (faster-whisper). Báo lỗi rõ ràng nếu chưa cài."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Cần cài faster-whisper để xác minh: pip install faster-whisper") from exc
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(path), language="vi", vad_filter=True)
    return " ".join(s.text.strip() for s in segments)


def verify_media(path: Path, challenge: Challenge, transcribe=transcribe_plain) -> VerifyResult:
    return check_transcript(transcribe(path), challenge)


def extract_reference_frames(video: Path, out_dir: Path, count: int = 5) -> list[str]:
    """Lấy khung hình rải đều trong video đồng ý (người đó quay thẳng, nghiêng trái/phải, lùi xa)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                         check=True, capture_output=True, text=True).stdout.strip()
    duration = float(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        frame = out_dir / f"ref_{i + 1}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-q:v", "2", str(frame)], check=True)
        frames.append(str(frame))
    return frames
