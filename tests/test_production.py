"""Kiểm thử xác minh đồng ý, ghép video và lệnh gửi nền tảng (không gọi API thật)."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from agent_thoi_trang import consent
from agent_thoi_trang.models import Scene, ScoredScript, Script
from agent_thoi_trang.production import get_status, media_duration, produce
from agent_thoi_trang.store import Consent, Presenter, Voice, now
from agent_thoi_trang.video_gen import ClipRequest, build_prompt


# ---------- Xác minh đồng ý ----------

CH = consent.Challenge(person_name="Nguyễn Thu Hà", code="4207", day=date(2026, 11, 25), purpose="khuôn mặt và giọng nói")


def test_statement_contains_code_and_date():
    assert "4 2 0 7" in CH.statement and "25 tháng 11 năm 2026" in CH.statement


def test_transcript_pass_with_digits_or_words():
    ok = consent.check_transcript(
        "Tôi là Nguyễn Thu Hà, hôm nay là ngày 25 tháng 11 năm 2026. Mã xác nhận của tôi là bốn hai không bảy. "
        "Tôi đồng ý cho agent video thời trang sử dụng khuôn mặt và giọng nói của tôi.", CH)
    assert ok.passed, ok.reasons
    ok2 = consent.check_transcript(CH.statement.replace("4 2 0 7", "4207"), CH)
    assert ok2.passed


@pytest.mark.parametrize("text,reason", [
    ("Tôi là Nguyễn Thu Hà. Mã xác nhận là 1111. Tôi đồng ý cho agent dùng khuôn mặt.", "mã"),
    ("Xin chào mọi người hôm nay mình review quần jeans ống loe nhé", "mã"),
    (CH.statement.replace("Nguyễn Thu Hà", "Trần Văn B"), "tên"),
    (CH.statement.replace("đồng ý", "không muốn"), "đồng ý"),
])
def test_transcript_fail(text, reason):
    r = consent.check_transcript(text, CH)
    assert not r.passed
    assert any(reason in x for x in r.reasons)


def test_extra_reading_after_statement_still_passes():
    assert consent.check_transcript(CH.statement + " " + consent.SAMPLE_PARAGRAPH, CH).passed


def test_new_challenge_codes_are_random():
    codes = {consent.new_challenge("A", "giọng nói").code for _ in range(20)}
    assert len(codes) > 1


# ---------- Prompt gửi nền tảng ----------

def test_prompt_pins_presenter_and_product():
    req = ClipRequest(prompt="She twirls in the studio.", presenter_images=["a.jpg", "b.jpg"], product_images=["p.png"])
    p = build_prompt(req, "fictional woman")
    assert "<IMAGE_REF_0> <IMAGE_REF_1>" in p and "<IMAGE_REF_2>" in p
    assert "No one speaks" in p and "9:16" in p


# ---------- Ghép video ----------

def _fake_clip(provider, req, desc, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=24:d={req.duration_s}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={req.duration_s}", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
    _fake_clip.calls.append(req)
    return out


_fake_clip.calls = []


def _fake_tts(voice, text, out: Path) -> Path:
    secs = 10 if "dài" in text else 2
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=600:duration={secs}",
                    str(out)], check=True)
    return out


def _script() -> ScoredScript:
    scenes = [Scene(index=1, duration_s=4, visual="v", camera="c", voiceover="Chào mấy bà", on_screen_text="SALE 50%",
                    veo_prompt="p1"),
              Scene(index=2, duration_s=4, visual="v", camera="c", voiceover="Lời đọc dài hơn clip", on_screen_text="",
                    veo_prompt="p2"),
              Scene(index=3, duration_s=4, visual="v", camera="c", voiceover="", on_screen_text="Mua ngay", veo_prompt="p3")]
    s = Script(script_id="KB001", title="t", format="f", product="jeans", hook="h", scenes=scenes, cta="c",
               caption="cap", hashtags=["#a"], music_suggestion="m")
    return ScoredScript(script=s, score_cards=[], total=95)


def test_produce_builds_draft(tmp_path):
    _fake_clip.calls.clear()
    presenter = Presenter(id="p", name="Mây", kind="ai_original", description_en="d", images=["ref.jpg"], created_at=now())
    voice = Voice(id="v", name="v", provider="google_tts", provider_voice_id="x")
    res = produce(_script(), presenter, voice, ["prod.png"], "omni", tmp_path, log=lambda m: None,
                  clip_fn=_fake_clip, tts_fn=_fake_tts)
    folder = res.folder
    timeline = json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    # cảnh 2: lời đọc 10s dài hơn clip 4s -> cảnh kéo dài theo lời đọc
    lengths = [s["end_s"] - s["start_s"] for s in timeline["scenes"]]
    assert lengths[1] > 10 and abs(lengths[0] - 4) < 0.2
    assert abs(media_duration(res.preview) - sum(lengths)) < 0.5
    assert (folder / "voice" / "scene_01.mp3").exists() and not (folder / "voice" / "scene_03.mp3").exists()
    assert "SALE 50%" in (folder / "text_overlays.srt").read_text(encoding="utf-8")
    assert get_status(folder)["status"] == "chờ duyệt"
    assert all(r.presenter_images == ["ref.jpg"] and r.product_images == ["prod.png"] for r in _fake_clip.calls)


def test_produce_refuses_unverified_real_person(tmp_path):
    real = Presenter(id="r", name="R", kind="real_person", description_en="d", created_at=now(),
                     consent=Consent(person_name="R", statement="s", verified=False))
    voice = Voice(id="v", name="v", provider="google_tts", provider_voice_id="x")
    with pytest.raises(ValueError):
        produce(_script(), real, voice, [], "omni", tmp_path, clip_fn=_fake_clip, tts_fn=_fake_tts)
