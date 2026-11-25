"""Sản xuất video từ một kịch bản đã chọn và xuất bản nháp chỉnh sửa được.

Thư mục kết quả cho mỗi kịch bản:
  clips/scene_XX.mp4     clip video từng cảnh (từ Gemini Omni hoặc Grok)
  voice/scene_XX.mp3     lời đọc từng cảnh (giọng đã chọn)
  subtitles.srt          phụ đề lời đọc
  text_overlays.srt      chữ trên màn hình theo cảnh
  timeline.json          mốc thời gian từng cảnh, file nào, chữ gì (để dựng lại ở CapCut/Premiere)
  preview.mp4            bản xem thử đã ghép voice + chữ
  status.json            trạng thái duyệt
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import ScoredScript
from .store import Presenter, Voice
from .tts import synthesize
from .video_gen import ClipRequest, generate_clip

ClipFn = Callable[[str, ClipRequest, str, Path], Path]
TTSFn = Callable[[Voice, str, Path], Path]


def media_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout.strip()
    return float(out)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: Path, entries: list[tuple[float, float, str]]) -> None:
    blocks = [f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n"
              for i, (a, b, text) in enumerate(((a, b, t) for a, b, t in entries if t.strip()), start=1)]
    path.write_text("\n".join(blocks), encoding="utf-8")


@dataclass
class ProductionResult:
    script_id: str
    folder: Path
    preview: Path
    duration_s: float


def _render_scene(clip: Path, voice: Path | None, length: float, out: Path) -> None:
    """Chuẩn hoá cảnh về 720x1280/30fps, kéo dài khung cuối nếu lời đọc dài hơn clip, trộn voice."""
    vf = (f"scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,"
          f"tpad=stop_mode=clone:stop_duration={length:.2f},trim=duration={length:.2f},setpts=PTS-STARTPTS")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(clip)]
    if voice:
        cmd += ["-i", str(voice)]
    has_clip_audio = bool(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(clip)],
        capture_output=True, text=True).stdout.strip())
    amb = (f"[0:a]volume=0.15,apad,atrim=duration={length:.2f}[amb]" if has_clip_audio
           else f"anullsrc=r=44100:cl=stereo,atrim=duration={length:.2f}[amb]")
    if voice:
        af = f"{amb};[1:a]apad,atrim=duration={length:.2f}[vo];[amb][vo]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        af = amb.replace("[amb]", "[a]")
    cmd += ["-filter_complex", f"[0:v]{vf}[v];{af}", "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out)]
    subprocess.run(cmd, check=True)


def produce(scored: ScoredScript, presenter: Presenter, voice: Voice, product_images: list[str], provider: str,
            out_root: Path, log: Callable[[str], None] = print,
            clip_fn: ClipFn = generate_clip, tts_fn: TTSFn = synthesize) -> ProductionResult:
    if not presenter.usable:
        raise ValueError(f"Người dẫn '{presenter.name}' chưa được xác minh đồng ý.")
    if not voice.usable:
        raise ValueError(f"Giọng '{voice.name}' chưa được xác minh đồng ý.")
    script = scored.script
    folder = out_root / script.script_id
    for sub in ("clips", "voice", "scenes"):
        (folder / sub).mkdir(parents=True, exist_ok=True)

    timeline, subs, overlays, t = [], [], [], 0.0
    for scene in script.scenes:
        tag = f"scene_{scene.index:02d}"
        log(f"{script.script_id} · cảnh {scene.index}/{len(script.scenes)}: tạo clip...")
        clip = folder / "clips" / f"{tag}.mp4"
        if not clip.exists():
            req = ClipRequest(prompt=scene.veo_prompt, presenter_images=presenter.images[:3],
                              product_images=product_images[:3], duration_s=max(4, round(scene.duration_s)))
            clip_fn(provider, req, presenter.description_en, clip)
        voice_file = None
        if scene.voiceover.strip():
            voice_file = folder / "voice" / f"{tag}.mp3"
            if not voice_file.exists():
                log(f"{script.script_id} · cảnh {scene.index}: đọc lời...")
                tts_fn(voice, scene.voiceover, voice_file)
        clip_len = media_duration(clip)
        voice_len = media_duration(voice_file) + 0.3 if voice_file else 0.0
        length = round(max(clip_len, voice_len, 1.0), 2)
        rendered = folder / "scenes" / f"{tag}.mp4"
        _render_scene(clip, voice_file, length, rendered)
        timeline.append({"index": scene.index, "start_s": round(t, 2), "end_s": round(t + length, 2),
                         "clip": f"clips/{tag}.mp4", "voice": f"voice/{tag}.mp3" if voice_file else None,
                         "voiceover": scene.voiceover, "on_screen_text": scene.on_screen_text,
                         "prompt": scene.veo_prompt})
        subs.append((t, t + length, scene.voiceover))
        overlays.append((t, t + length, scene.on_screen_text))
        t += length

    write_srt(folder / "subtitles.srt", subs)
    write_srt(folder / "text_overlays.srt", overlays)
    concat = folder / "scenes" / "list.txt"
    concat.write_text("".join(f"file '{(folder / 'scenes' / f'scene_{s.index:02d}.mp4').resolve()}'\n"
                              for s in script.scenes), encoding="utf-8")
    joined = folder / "scenes" / "joined.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-c", "copy", str(joined)], check=True)
    preview = folder / "preview.mp4"
    style = "FontName=Arial,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=6,MarginV=40"
    srt_path = str((folder / "text_overlays.srt").resolve()).replace(":", r"\:")
    result = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(joined), "-vf",
                             f"subtitles='{srt_path}':force_style='{style}'", "-c:a", "copy", str(preview)],
                            capture_output=True, text=True)
    if result.returncode != 0:  # máy không có libass: giữ bản không chữ, chữ vẫn có trong text_overlays.srt
        log("Không chèn được chữ vào bản xem thử (thiếu libass); chữ vẫn nằm trong text_overlays.srt.")
        joined.replace(preview)
    meta = {"script_id": script.script_id, "title": script.title, "score": scored.total, "provider": provider,
            "presenter": presenter.name, "voice": voice.name, "duration_s": round(t, 2),
            "caption": script.caption, "hashtags": script.hashtags, "music_suggestion": script.music_suggestion,
            "scenes": timeline}
    (folder / "timeline.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    set_status(folder, "chờ duyệt")
    return ProductionResult(script.script_id, folder, preview, round(t, 2))


def set_status(folder: Path, status: str, note: str = "") -> None:
    (folder / "status.json").write_text(json.dumps({"status": status, "note": note}, ensure_ascii=False),
                                        encoding="utf-8")


def get_status(folder: Path) -> dict:
    f = folder / "status.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"status": "chưa tạo", "note": ""}
