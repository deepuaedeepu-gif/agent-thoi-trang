"""Bước 4: viết kịch bản (kèm prompt Veo cho từng cảnh) theo công thức kênh."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from .llm import LLM, image_block, text_block
from .models import ChannelFormula, Script, ScriptBatch


def presenter_sheet(presenter_cfg: dict) -> str:
    mode = presenter_cfg.get("mode", "ai_original")
    if mode == "owner":
        owner = presenter_cfg.get("owner", {})
        if not owner.get("verified"):
            raise ValueError("Chế độ 'owner' chỉ dùng được sau khi đã xác minh danh tính (owner.verified: true).")
        return owner.get("description_en", "")
    return presenter_cfg["ai_original"]["description_en"]


WRITER_SYSTEM = """Bạn là biên kịch video ngắn thời trang cho Facebook Reels, dựng bằng Google Veo.
Viết kịch bản tiếng Việt bám sát CÔNG THỨC KÊNH được cung cấp, xoay quanh SẢN PHẨM được cung cấp.
Quy tắc:
- Mỗi cảnh tối đa 8 giây (một clip Veo), video dọc 9:16, tổng độ dài theo công thức.
- Luôn dùng đúng người dẫn trong PRESENTER SHEET; chép nguyên mô tả ngoại hình vào mọi veo_prompt
  để nhân vật nhất quán. Không mô tả hay bắt chước bất kỳ người thật nào.
- veo_prompt viết bằng tiếng Anh, cụ thể: nhân vật, trang phục (đúng sản phẩm), hành động, bối cảnh,
  góc máy, chuyển động máy, ánh sáng, "vertical 9:16". Không đưa chữ vào prompt (chữ được chèn khi dựng).
- Hook 3 giây đầu phải cụ thể và khiến người xem dừng lướt.
- Các kịch bản phải khác nhau rõ rệt về góc tiếp cận, không chỉ đổi chữ.
- Không dùng nhạc có bản quyền cụ thể; chỉ gợi ý mood nhạc."""


def write_scripts(
    llm: LLM,
    formula: ChannelFormula,
    products: dict,
    presenter_cfg: dict,
    count: int,
    id_prefix: str = "KB",
    start_index: int = 1,
    product_images: Sequence[str | Path] = (),
    voice: dict | None = None,
) -> list[Script]:
    voice_line = f"GIỌNG ĐỌC ĐÃ CHỌN: {json.dumps(voice, ensure_ascii=False)}\n\n" if voice else ""
    prompt = (
        f"CÔNG THỨC KÊNH:\n{formula.model_dump_json(indent=1)}\n\n"
        f"SẢN PHẨM VÀ BỐI CẢNH:\n{json.dumps(products, ensure_ascii=False, indent=1)}\n\n"
        f"PRESENTER SHEET:\n{presenter_sheet(presenter_cfg)}\n\n{voice_line}"
        f"Hãy viết {count} kịch bản. Đặt script_id lần lượt từ {id_prefix}{start_index:03d}."
    )
    content = [text_block(prompt)]
    if product_images:
        content.append(text_block(
            "ẢNH SẢN PHẨM THẬT (bắt buộc dùng đúng sản phẩm này; mô tả chính xác màu, chất liệu, chi tiết "
            "trong mọi veo_prompt; khi dựng video, ảnh này được gửi kèm làm ảnh tham chiếu):"))
        content += [image_block(p) for p in product_images]
    batch = llm.parse(WRITER_SYSTEM, content, ScriptBatch, effort="high")
    return batch.scripts


REWRITE_SYSTEM = WRITER_SYSTEM + """
Bạn đang VIẾT LẠI một kịch bản đã được chấm điểm. Giữ ý tưởng cốt lõi và script_id,
sửa đúng các điểm yếu trong góp ý để đạt trên 90 điểm."""


def rewrite_script(
    llm: LLM, script: Script, notes: list[str], formula: ChannelFormula, presenter_cfg: dict
) -> Script:
    prompt = (
        f"CÔNG THỨC KÊNH:\n{formula.model_dump_json(indent=1)}\n\n"
        f"PRESENTER SHEET:\n{presenter_sheet(presenter_cfg)}\n\n"
        f"KỊCH BẢN HIỆN TẠI:\n{script.model_dump_json(indent=1)}\n\n"
        "GÓP Ý CẦN SỬA:\n" + "\n".join(f"- {n}" for n in notes)
    )
    batch = llm.parse(REWRITE_SYSTEM, [text_block(prompt + "\n\nTrả về đúng 1 kịch bản.")], ScriptBatch)
    new = batch.scripts[0]
    return new.model_copy(update={"script_id": script.script_id})
