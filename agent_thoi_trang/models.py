"""Kiểu dữ liệu dùng chung cho cả pipeline (Pydantic, dùng làm structured output cho Claude)."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- Bước 1-2: phân tích từng video mẫu ----------

class VideoMetrics(BaseModel):
    """Số liệu tương tác, nhập tay hoặc từ file CSV (Facebook không cho đọc tự động)."""

    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None


class TechnicalStats(BaseModel):
    """Số liệu đo bằng ffmpeg, không cần AI."""

    duration_s: float
    width: int
    height: int
    scene_cut_times_s: list[float]
    cuts_per_10s: float
    has_audio: bool


class VideoAnalysis(BaseModel):
    """Claude điền phần này từ khung hình + lời thoại."""

    hook_first_3s: str = Field(description="Mô tả chính xác điều gì xảy ra trong 3 giây đầu")
    hook_type: str = Field(description="Ví dụ: cầm sản phẩm lên khoe, câu hỏi, tương phản trước/sau, POV, giá sốc")
    format: str = Field(description="Ví dụ: try-on, outfit check, phối đồ theo dịp, review chất liệu, lookbook ngoài phố")
    product_focus: str = Field(description="Sản phẩm chính và cách khoe (cận chất liệu, xoay người, so sánh)")
    setting: str = Field(description="Bối cảnh, ánh sáng, đạo cụ")
    camera_style: str = Field(description="Góc máy, cầm tay hay cố định, khoảng cách")
    on_screen_text: list[str] = Field(description="Chữ trên màn hình theo thứ tự xuất hiện")
    voice_style: str = Field(description="Giọng nói: tốc độ, năng lượng, xưng hô (không nhận dạng danh tính)")
    music_mood: str
    cta: str = Field(description="Lời kêu gọi hành động, nếu có")
    structure: list[str] = Field(description="Các đoạn theo thời gian, ví dụ '0-3s: hook ...'")
    strengths: list[str]
    weaknesses: list[str]


class AnalyzedVideo(BaseModel):
    video_id: str
    source_path: str
    caption: str | None = None
    metrics: VideoMetrics = VideoMetrics()
    stats: TechnicalStats
    transcript: str | None = None
    analysis: VideoAnalysis | None = None


# ---------- Bước 3: công thức kênh ----------

class WinningFormat(BaseModel):
    name: str
    description: str
    example_video_ids: list[str]


class ChannelFormula(BaseModel):
    summary: str
    winning_formats: list[WinningFormat]
    hook_patterns: list[str]
    ideal_duration_s: str
    pacing: str = Field(description="Nhịp cắt chuẩn, ví dụ '3-4 cảnh mỗi 10 giây'")
    visual_style: str
    text_overlay_style: str
    voice_style: str
    cta_patterns: list[str]
    do_list: list[str]
    dont_list: list[str]
    confidence_note: str = Field(description="Độ tin cậy, nói rõ nếu ít video hoặc thiếu số liệu tương tác")


# ---------- Bước 4: kịch bản ----------

class Scene(BaseModel):
    index: int
    duration_s: float = Field(description="Tối đa 8 giây, khớp độ dài một clip Veo")
    visual: str = Field(description="Mô tả hình ảnh bằng tiếng Việt")
    camera: str
    voiceover: str = Field(description="Lời thoại tiếng Việt của cảnh, có thể rỗng")
    on_screen_text: str
    veo_prompt: str = Field(
        description="Prompt tiếng Anh cho Veo, có mô tả người dẫn theo presenter sheet, trang phục, bối cảnh, "
        "góc máy, ánh sáng, chuyển động, tỉ lệ 9:16"
    )


class Script(BaseModel):
    script_id: str
    title: str
    format: str
    product: str
    hook: str
    scenes: list[Scene]
    cta: str
    caption: str
    hashtags: list[str]
    music_suggestion: str


class ScriptBatch(BaseModel):
    scripts: list[Script]


# ---------- Bước 5: chấm điểm ----------

class CriterionScore(BaseModel):
    criterion: str
    score: float
    max_score: float
    reason: str


class ScoreCard(BaseModel):
    criteria: list[CriterionScore]
    improvement_notes: list[str] = Field(description="Góp ý cụ thể để kịch bản đạt trên 90")

    @property
    def total(self) -> float:
        return round(sum(min(c.score, c.max_score) for c in self.criteria), 1)


class ScoredScript(BaseModel):
    script: Script
    score_cards: list[ScoreCard]
    total: float
    revision: int = 0
