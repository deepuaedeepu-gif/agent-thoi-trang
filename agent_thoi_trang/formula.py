"""Bước 3: so sánh video top với phần còn lại để rút ra công thức kênh."""

from __future__ import annotations

from .llm import LLM, text_block
from .models import AnalyzedVideo, ChannelFormula


def engagement_score(v: AnalyzedVideo) -> float | None:
    """Tương tác có trọng số; bình luận và chia sẻ nặng hơn lượt thích."""
    m = v.metrics
    if m.views is None and m.likes is None:
        return None
    interactions = (m.likes or 0) + 3 * (m.comments or 0) + 5 * (m.shares or 0)
    return interactions / m.views if m.views else float(interactions)


def rank_videos(videos: list[AnalyzedVideo], top_fraction: float = 0.2) -> tuple[list[AnalyzedVideo], list[AnalyzedVideo]]:
    """Chia nhóm top / còn lại. Không có số liệu thì coi mọi video là mẫu ngang nhau."""
    scored = [(engagement_score(v), v) for v in videos]
    if all(s is None for s, _ in scored):
        return videos, []
    scored.sort(key=lambda x: x[0] if x[0] is not None else -1, reverse=True)
    k = max(1, round(len(scored) * top_fraction))
    return [v for _, v in scored[:k]], [v for _, v in scored[k:]]


FORMULA_SYSTEM = """Bạn là chiến lược gia nội dung thời trang trên Facebook Reels.
Từ phân tích các video của kênh mẫu, hãy rút ra CÔNG THỨC THÀNH CÔNG có thể lặp lại:
format thắng, mẫu hook, độ dài, nhịp cắt, phong cách hình/chữ/giọng, CTA, nên và không nên.
Ưu tiên điểm khác biệt giữa nhóm TOP và nhóm CÒN LẠI. Nếu ít dữ liệu, nói rõ trong confidence_note.
Công thức chỉ mô tả phong cách, không gắn với danh tính người trong video. Trả lời bằng tiếng Việt."""


def _describe(v: AnalyzedVideo) -> str:
    return v.model_dump_json(exclude={"source_path"}, indent=1)


def build_formula(llm: LLM, videos: list[AnalyzedVideo]) -> ChannelFormula:
    top, rest = rank_videos(videos)
    parts = [f"Tổng số video: {len(videos)}. Nhóm TOP ({len(top)} video):"]
    parts += [_describe(v) for v in top]
    if rest:
        parts.append(f"Nhóm CÒN LẠI ({len(rest)} video):")
        parts += [_describe(v) for v in rest]
    else:
        parts.append("Không có số liệu tương tác để chia nhóm; hãy coi tất cả là mẫu tham khảo.")
    return llm.parse(FORMULA_SYSTEM, [text_block("\n\n".join(parts))], ChannelFormula, effort="high")
