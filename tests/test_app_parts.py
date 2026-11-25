"""Kiểm thử kho dữ liệu, hàm quét Facebook (phần không cần mạng) và giao diện app."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_thoi_trang.facebook_scan import canonical_reel, parse_count, pick_top, reels_tab_url
from agent_thoi_trang.store import Consent, Presenter, Store, Voice, now


@pytest.mark.parametrize("text,expected", [
    ("1,2K", 1200), ("1.2K", 1200), ("12 N", 12000), ("3,4 Tr", 3400000), ("987", 987),
    ("2,5 triệu lượt xem", 2500000), ("1.234", 1234), ("", None), ("không có số", None),
])
def test_parse_count(text, expected):
    assert parse_count(text) == expected


def test_reels_tab_url():
    assert reels_tab_url("https://www.facebook.com/profile.php?id=61582493828073") == \
        "https://www.facebook.com/profile.php?id=61582493828073&sk=reels_tab"
    assert reels_tab_url("https://www.facebook.com/profile.php?id=1&sk=reels_tab").endswith("sk=reels_tab")
    assert reels_tab_url("https://www.facebook.com/somepage") == "https://www.facebook.com/somepage/reels/"
    assert reels_tab_url("https://www.facebook.com/reel/123456") is None


def test_canonical_and_pick_top():
    assert canonical_reel("https://www.facebook.com/reel/987?s=x") == "https://www.facebook.com/reel/987"
    items = [{"url": "a", "views": None}, {"url": "b", "views": 50}, {"url": "c", "views": 900}]
    assert [i["url"] for i in pick_top(items, 2)] == ["c", "b"]


def test_store_seed_and_consent_gate(tmp_path):
    s = Store(tmp_path)
    assert [p.kind for p in s.presenters()] == ["ai_original"]
    assert len(s.voices()) == 10 and all(v.usable for v in s.voices())

    real = Presenter(id="x", name="X", kind="real_person", description_en="d", created_at=now())
    assert not real.usable
    with pytest.raises(ValueError):
        real.as_presenter_cfg()
    real.consent = Consent(person_name="X", statement="đồng ý", consent_video="v.mp4", verified=True)
    assert real.as_presenter_cfg()["owner"]["verified"] is True

    cloned = Voice(id="c", name="c", provider="elevenlabs", provider_voice_id="1", kind="cloned")
    assert not cloned.usable


def test_save_file_sanitizes_name(tmp_path):
    s = Store(tmp_path)
    path = Path(s.save_file("products", "p1", "../../evil name.png", b"x"))
    assert path.parent == tmp_path / "products" / "p1"
    assert path.name == "evil_name.png"


def test_app_renders(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(str(Path(__file__).parents[1] / "app" / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert labels == ["📈 Công thức thành công", "🧍 Kho Người mẫu", "🎙️ Kho voice", "🎬 Dựng video", "⚙️ Cài đặt"]


def test_settings_save_load_apply(tmp_path, monkeypatch):
    import os

    from agent_thoi_trang import settings

    f = tmp_path / "s.json"
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "SETTINGS_FILE", f)
    monkeypatch.setattr(settings, "load", lambda path=f: settings.json.loads(f.read_text()) if f.exists() else {})
    settings.save({"XAI_API_KEY": " xai-123 ", "GEMINI_API_KEY": ""}, path=f)
    assert settings.json.loads(f.read_text()) == {"XAI_API_KEY": "xai-123"}
    assert os.environ["XAI_API_KEY"] == "xai-123"
    settings.save({}, path=f)
    assert "XAI_API_KEY" not in os.environ
    assert all(spec.guide.strip().startswith("1.") for spec in settings.KEYS)
