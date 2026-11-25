"""Kiểm thử pipeline bằng LLM giả (không tốn tiền API)."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from agent_thoi_trang import config
from agent_thoi_trang.pipeline import ScriptJob, generate_until_enough as _gen


def generate_until_enough(llm, formula, products, presenter, batch_size, max_scripts, **kw):
    return _gen(llm, ScriptJob(formula=formula, products=products, presenter=presenter,
                               batch_size=batch_size, max_scripts=max_scripts, **kw), log=lambda m: None)
from agent_thoi_trang.export import write_outputs
from agent_thoi_trang.formula import rank_videos
from agent_thoi_trang.models import (
    AnalyzedVideo, ChannelFormula, CriterionScore, Scene, ScoreCard, Script, ScriptBatch,
    TechnicalStats, VideoMetrics,
)
from agent_thoi_trang.scoring import normalize_card
from agent_thoi_trang.scripts import presenter_sheet

PRESENTER = config.load_yaml(Path(__file__).parents[1] / "config" / "presenter.yaml")
FORMULA = ChannelFormula(
    summary="s", winning_formats=[], hook_patterns=["h"], ideal_duration_s="30-45s", pacing="3 cảnh/10s",
    visual_style="v", text_overlay_style="t", voice_style="g", cta_patterns=["c"], do_list=[], dont_list=[],
    confidence_note="test",
)


def make_script(sid: str) -> Script:
    scene = Scene(index=1, duration_s=8, visual="v", camera="c", voiceover="o", on_screen_text="t", veo_prompt="p")
    return Script(script_id=sid, title=sid, format="try-on", product="jeans", hook="h", scenes=[scene],
                  cta="c", caption="cap", hashtags=["#a"], music_suggestion="m")


def card_with_total(total: float) -> ScoreCard:
    """Phân bổ tổng điểm theo tỉ lệ thang điểm."""
    return ScoreCard(
        criteria=[CriterionScore(criterion=n, score=mx * total / 100, max_score=mx, reason="r")
                  for n, mx, _ in config.RUBRIC],
        improvement_notes=["sửa hook"],
    )


class FakeLLM:
    def __init__(self, scores):
        self.scores = iter(scores)
        self.counter = itertools.count(1)
        self.calls: list[str] = []

    def parse(self, system, content, schema, effort="high"):
        self.calls.append(schema.__name__)
        if schema is ScoreCard:
            return card_with_total(next(self.scores))
        if schema is ScriptBatch:
            text = content[0]["text"]
            n = 1 if "Trả về đúng 1 kịch bản" in text else int(text.split("Hãy viết ")[1].split()[0])
            return ScriptBatch(scripts=[make_script(f"KB{next(self.counter):03d}") for _ in range(n)])
        raise AssertionError(schema)


def test_normalize_card_clamps_and_fills():
    card = ScoreCard(criteria=[CriterionScore(criterion="x", score=40, max_score=40, reason="r")], improvement_notes=[])
    fixed = normalize_card(card)
    assert len(fixed.criteria) == len(config.RUBRIC)
    assert fixed.criteria[0].score == 25  # bị ép về mức tối đa của tiêu chí 1
    assert fixed.total == 25


def test_selects_ten_and_rewrites_80s(monkeypatch):
    monkeypatch.setattr(config, "JUDGE_PASSES", 1)
    # Lô 1 (10 bản): 6 bản 95, 2 bản 85 -> viết lại thành 92, 2 bản 70.
    # Lô 2 (10 bản): toàn 93.
    scores = [95] * 6 + [85, 92, 85, 92] + [70, 70] + [93] * 10
    llm = FakeLLM(scores)
    import agent_thoi_trang.scoring as scoring
    monkeypatch.setattr(scoring.config, "JUDGE_PASSES", 1)
    all_scored, selected = generate_until_enough(llm, FORMULA, {"products": []}, PRESENTER, batch_size=10, max_scripts=40)
    assert len(all_scored) == 20  # dừng sau lô 2 vì đã đủ 10
    assert len(selected) == 10
    assert all(s.total >= 90 for s in selected)
    assert selected[0].total == 95
    assert sum(1 for s in all_scored if s.revision == 1) == 2


def test_stops_at_max_scripts(monkeypatch):
    import agent_thoi_trang.scoring as scoring
    monkeypatch.setattr(scoring.config, "JUDGE_PASSES", 1)
    llm = FakeLLM([60] * 100)
    all_scored, selected = generate_until_enough(llm, FORMULA, {}, PRESENTER, batch_size=5, max_scripts=10)
    assert len(all_scored) == 10 and selected == []


def test_rewrite_rounds_are_capped(monkeypatch):
    import agent_thoi_trang.scoring as scoring
    monkeypatch.setattr(scoring.config, "JUDGE_PASSES", 1)
    llm = FakeLLM([85, 84, 83])  # không bao giờ lên 90
    all_scored, _ = generate_until_enough(llm, FORMULA, {}, PRESENTER, batch_size=1, max_scripts=1)
    assert all_scored[0].revision == config.MAX_REWRITE_ROUNDS
    assert all_scored[0].total == 85  # giữ bản tốt nhất


def test_owner_mode_requires_verification():
    cfg = {"mode": "owner", "owner": {"verified": False, "description_en": "x"}}
    with pytest.raises(ValueError):
        presenter_sheet(cfg)
    assert "fictional" in presenter_sheet(PRESENTER)


def test_rank_videos_by_engagement():
    def v(i, views, likes):
        return AnalyzedVideo(video_id=str(i), source_path="", metrics=VideoMetrics(views=views, likes=likes),
                             stats=TechnicalStats(duration_s=10, width=1, height=1, scene_cut_times_s=[],
                                                  cuts_per_10s=0, has_audio=True))
    top, rest = rank_videos([v(i, 1000, i * 10) for i in range(10)])
    assert [x.video_id for x in top] == ["9", "8"]
    assert len(rest) == 8


def test_write_outputs(tmp_path, monkeypatch):
    import agent_thoi_trang.scoring as scoring
    monkeypatch.setattr(scoring.config, "JUDGE_PASSES", 1)
    llm = FakeLLM([95])
    all_scored, selected = generate_until_enough(llm, FORMULA, {}, PRESENTER, batch_size=1, max_scripts=1)
    write_outputs(tmp_path, FORMULA, all_scored, selected)
    assert "95.0 điểm" in (tmp_path / "selected_scripts.md").read_text(encoding="utf-8")
    assert "KB001" in (tmp_path / "veo_prompts.txt").read_text(encoding="utf-8")


def test_custom_threshold_and_count(monkeypatch):
    import agent_thoi_trang.scoring as scoring
    monkeypatch.setattr(scoring.config, "JUDGE_PASSES", 1)
    llm = FakeLLM([86, 80, 84, 83, 70])  # 80 (khoảng viết lại 75-84) -> 84 -> 83; 70 không viết lại
    all_scored, selected = generate_until_enough(llm, FORMULA, {}, PRESENTER, batch_size=3, max_scripts=3,
                                                 target_count=2, pass_score=85)
    assert [s.total for s in selected] == [86]
    assert [s.total for s in all_scored] == [86, 84, 70]
    assert [s.revision for s in all_scored] == [0, 2, 0]
