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
    assert not any(spec.required for spec in settings.KEYS)


def test_claude_code_backend_parses_result(monkeypatch):
    import json as _json

    from pydantic import BaseModel

    from agent_thoi_trang import llm

    class Out(BaseModel):
        reply: str

    events = [{"type": "system", "subtype": "init"},
              {"type": "result", "is_error": False, "structured_output": {"reply": "Đã kết nối"}}]
    stdout = "\n".join(_json.dumps(e, ensure_ascii=False) for e in events)
    assert llm.ClaudeCodeLLM.read_result(stdout, "", Out).reply == "Đã kết nối"
    # Không có structured_output: đọc JSON trong result
    stdout2 = _json.dumps({"type": "result", "is_error": False, "result": '```json\n{"reply": "ok"}\n```'})
    assert llm.ClaudeCodeLLM.read_result(stdout2, "", Out).reply == "ok"
    err = _json.dumps({"type": "result", "is_error": True, "result": "Not logged in"})
    with pytest.raises(RuntimeError, match="Not logged in"):
        llm.ClaudeCodeLLM.read_result(err, "", Out)


def test_claude_code_command_disables_tools_and_hides_api_key(monkeypatch, tmp_path):
    from pydantic import BaseModel

    from agent_thoi_trang import llm

    class Out(BaseModel):
        reply: str

    seen = {}

    def fake_run(cmd, input, env, **kw):
        seen.update(cmd=cmd, input=input, env=env)

        class P:
            stdout = '{"type": "result", "is_error": false, "structured_output": {"reply": "x"}}'
            stderr = ""
        return P()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    out = llm.ClaudeCodeLLM(executable="/usr/bin/claude").parse(
        "sys", [llm.text_block("hi"), {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA"}}], Out)
    assert out.reply == "x"
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "" and "--json-schema" in cmd and "-p" in cmd
    assert "ANTHROPIC_API_KEY" not in seen["env"]
    assert '"image"' in seen["input"]


def test_make_llm_respects_backend(monkeypatch):
    from agent_thoi_trang import llm

    monkeypatch.setattr(llm, "claude_code_path", lambda: "/usr/bin/claude")
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    assert isinstance(llm.make_llm(), llm.ClaudeCodeLLM)
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert isinstance(llm.make_llm(), llm.ClaudeLLM)
