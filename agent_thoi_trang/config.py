"""Cấu hình chung: model, thang điểm, ngưỡng chọn kịch bản."""

from __future__ import annotations

from pathlib import Path

import yaml

MODEL = "claude-opus-5-5"

# Thang điểm 100 (khớp bản thiết kế). Thứ tự quan trọng: Claude chấm đúng thứ tự này.
RUBRIC: list[tuple[str, float, str]] = [
    ("Sức mạnh hook 3 giây đầu", 25, "Người xem có dừng lướt không? Hook có cụ thể, bất ngờ, liên quan sản phẩm?"),
    ("Khớp công thức kênh", 20, "Format, nhịp cắt, độ dài, phong cách chữ và giọng có đúng công thức đã rút ra?"),
    ("Sản phẩm rõ ràng, hấp dẫn", 15, "Người xem thấy rõ form, chất liệu, cách phối, lý do nên mua?"),
    ("Cảm xúc / giải trí", 15, "Có cá tính, nhịp vui, khoảnh khắc đáng nhớ hoặc đáng chia sẻ?"),
    ("CTA rõ, tự nhiên", 10, "Kêu gọi hành động cụ thể, không gượng ép?"),
    ("Khả thi khi dựng bằng Veo", 10, "Mỗi cảnh ≤ 8 giây, ít nhân vật, chuyển động đơn giản, giữ nhân vật nhất quán được?"),
    ("Tuân thủ chính sách", 5, "Không vi phạm bản quyền, không mạo danh người thật, không cam kết sai sự thật?"),
]

PASS_SCORE = 90.0
TARGET_COUNT = 10
REWRITE_MIN_SCORE = 80.0  # kịch bản 80-89 được viết lại theo góp ý
MAX_REWRITE_ROUNDS = 2
JUDGE_PASSES = 2  # số lượt chấm độc lập, lấy trung bình


def load_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
