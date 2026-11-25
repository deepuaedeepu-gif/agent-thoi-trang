"""Bước 1-2: đọc video mẫu từ thư mục, đo kỹ thuật bằng ffmpeg, chép lời, rồi nhờ Claude gắn nhãn.

Facebook chặn truy cập tự động, nên video mẫu phải được tải về thư mục `inputs/videos/`
(kèm file `inputs/videos/metadata.csv` tuỳ chọn: video_id,caption,views,likes,comments,shares).
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .llm import LLM, image_block, text_block
from .models import AnalyzedVideo, TechnicalStats, VideoAnalysis, VideoMetrics

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
SCENE_THRESHOLD = 0.3


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout + ""


def probe(path: Path) -> dict:
    out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    return json.loads(out)


def detect_scene_cuts(path: Path, threshold: float = SCENE_THRESHOLD) -> list[float]:
    """Trả về các mốc thời gian (giây) có chuyển cảnh, dùng bộ lọc scene của ffmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-vf", f"select='gt(scene,{threshold})',showinfo",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return [round(float(t), 2) for t in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]


def technical_stats(path: Path) -> TechnicalStats:
    info = probe(path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    duration = float(info["format"]["duration"])
    cuts = detect_scene_cuts(path)
    return TechnicalStats(
        duration_s=round(duration, 2),
        width=int(video["width"]),
        height=int(video["height"]),
        scene_cut_times_s=cuts,
        cuts_per_10s=round(len(cuts) / duration * 10, 2) if duration else 0.0,
        has_audio=any(s["codec_type"] == "audio" for s in info["streams"]),
    )


def extract_keyframes(path: Path, out_dir: Path, duration: float, count: int = 10) -> list[Path]:
    """Lấy khung hình: dày ở 3 giây đầu (hook), thưa dần về sau."""
    out_dir.mkdir(parents=True, exist_ok=True)
    hook_times = [0.2, 1.0, 2.0, 3.0]
    rest = max(count - len(hook_times), 1)
    later = [3.0 + (duration - 3.5) * (i + 1) / rest for i in range(rest)] if duration > 4 else []
    frames = []
    for i, t in enumerate(hook_times + later):
        if t >= duration:
            continue
        frame = out_dir / f"frame_{i:02d}_{t:05.1f}s.jpg"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
             "-vf", "scale=-2:720", str(frame)],
            check=True,
        )
        frames.append(frame)
    return frames


def transcribe(path: Path, model_size: str = "small") -> str | None:
    """Chép lời tiếng Việt bằng faster-whisper nếu đã cài; nếu chưa cài thì bỏ qua."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(path), language="vi", vad_filter=True)
        return "\n".join(f"[{s.start:05.1f}s] {s.text.strip()}" for s in segments) or None
    except Exception as exc:  # thiếu mạng tải model, file hỏng...: bỏ qua lời thoại, không dừng pipeline
        print(f"Cảnh báo: không chép lời được {path.name}: {exc}")
        return None


def load_metadata(folder: Path) -> dict[str, dict]:
    meta_file = folder / "metadata.csv"
    if not meta_file.exists():
        return {}
    with open(meta_file, encoding="utf-8") as f:
        return {row["video_id"]: row for row in csv.DictReader(f)}


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(str(value).replace(",", "").replace(".", "")) if value not in (None, "") else None
    except ValueError:
        return None


ANALYSIS_SYSTEM = """Bạn là chuyên gia phân tích video ngắn thời trang trên Facebook Reels.
Bạn nhận các khung hình theo thời gian, lời thoại (nếu có) và số liệu kỹ thuật của MỘT video.
Hãy mô tả cách video được làm: hook, format, nhịp, cách khoe sản phẩm, chữ, giọng, CTA.
Chỉ phân tích phong cách và kỹ thuật. Không nhận dạng, đặt tên hay mô tả danh tính người trong video.
Trả lời bằng tiếng Việt."""


def analyze_with_claude(llm: LLM, video: AnalyzedVideo, frames: list[Path]) -> VideoAnalysis:
    content: list[dict] = [text_block(
        f"Video {video.video_id}: dài {video.stats.duration_s}s, {video.stats.width}x{video.stats.height}, "
        f"{len(video.stats.scene_cut_times_s)} lần chuyển cảnh ({video.stats.cuts_per_10s} lần/10s), "
        f"mốc chuyển cảnh: {video.stats.scene_cut_times_s}.\n"
        f"Caption: {video.caption or '(không có)'}\n"
        f"Lời thoại:\n{video.transcript or '(chưa chép lời)'}"
    )]
    for frame in frames:
        content.append(text_block(f"Khung hình {frame.stem.split('_')[-1]}"))
        content.append(image_block(frame))
    return llm.parse(ANALYSIS_SYSTEM, content, VideoAnalysis, effort="medium")


def analyze_folder(folder: Path, llm: LLM | None, work_dir: Path, do_transcribe: bool = True) -> list[AnalyzedVideo]:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Cần cài ffmpeg trước.")
    metadata = load_metadata(folder)
    results = []
    for path in sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTS):
        vid = path.stem
        meta = metadata.get(vid, {})
        stats = technical_stats(path)
        video = AnalyzedVideo(
            video_id=vid,
            source_path=str(path),
            caption=meta.get("caption") or None,
            metrics=VideoMetrics(**{k: _int_or_none(meta.get(k)) for k in ("views", "likes", "comments", "shares")}),
            stats=stats,
            transcript=transcribe(path) if do_transcribe and stats.has_audio else None,
        )
        if llm is not None:
            with tempfile.TemporaryDirectory() as tmp:
                frames = extract_keyframes(path, Path(tmp), stats.duration_s)
                video.analysis = analyze_with_claude(llm, video, frames)
        out = work_dir / "analyses" / f"{vid}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(video.model_dump_json(indent=2), encoding="utf-8")
        results.append(video)
    return results
