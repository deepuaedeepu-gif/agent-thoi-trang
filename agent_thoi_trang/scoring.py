"""Bước 5: chấm điểm kịch bản (2 lượt độc lập), viết lại bản 80-89, chọn 10 bản ≥ 90."""

from __future__ import annotations

from collections.abc import Callable

from . import config
from .llm import LLM, text_block
from .models import ChannelFormula, CriterionScore, ScoreCard, ScoredScript, Script

JUDGE_SYSTEM = """Bạn là giám khảo khó tính chấm kịch bản video ngắn thời trang cho Facebook Reels.
Chấm theo đúng thang điểm được cung cấp, đúng thứ tự tiêu chí, không cho điểm vượt mức tối đa.
Chỉ cho 90+ khi kịch bản thực sự xuất sắc và sẵn sàng sản xuất. Lý do ngắn gọn, cụ thể.
Góp ý phải là hành động sửa cụ thể. Trả lời bằng tiếng Việt."""


def rubric_text() -> str:
    return "\n".join(f"{i + 1}. {name} (tối đa {mx}): {hint}" for i, (name, mx, hint) in enumerate(config.RUBRIC))


def normalize_card(card: ScoreCard) -> ScoreCard:
    """Ép phiếu điểm về đúng thang: đúng tên, đúng mức tối đa, điểm trong [0, max]."""
    fixed = []
    for i, (name, mx, _) in enumerate(config.RUBRIC):
        got = card.criteria[i] if i < len(card.criteria) else CriterionScore(
            criterion=name, score=0, max_score=mx, reason="Giám khảo không chấm tiêu chí này")
        fixed.append(CriterionScore(criterion=name, score=max(0.0, min(got.score, mx)), max_score=mx, reason=got.reason))
    return ScoreCard(criteria=fixed, improvement_notes=card.improvement_notes)


def score_script(llm: LLM, script: Script, formula: ChannelFormula, passes: int | None = None) -> list[ScoreCard]:
    passes = passes or config.JUDGE_PASSES
    prompt = (
        f"THANG ĐIỂM (tổng 100):\n{rubric_text()}\n\n"
        f"CÔNG THỨC KÊNH:\n{formula.model_dump_json(indent=1)}\n\n"
        f"KỊCH BẢN:\n{script.model_dump_json(indent=1)}"
    )
    return [normalize_card(llm.parse(JUDGE_SYSTEM, [text_block(prompt)], ScoreCard, effort="medium"))
            for _ in range(passes)]


def average(cards: list[ScoreCard]) -> float:
    return round(sum(c.total for c in cards) / len(cards), 1)


def select_top(scored: list[ScoredScript], target: int | None = None,
               pass_score: float | None = None) -> list[ScoredScript]:
    target = target or config.TARGET_COUNT
    pass_score = config.PASS_SCORE if pass_score is None else pass_score
    passing = [s for s in scored if s.total >= pass_score]
    return sorted(passing, key=lambda s: s.total, reverse=True)[:target]


def score_and_improve(
    llm: LLM,
    scripts: list[Script],
    formula: ChannelFormula,
    rewrite: Callable[[Script, list[str]], Script],
    log: Callable[[str], None] = print,
    pass_score: float | None = None,
) -> list[ScoredScript]:
    """Chấm tất cả; kịch bản thiếu tối đa 10 điểm so với ngưỡng được viết lại theo góp ý
    (tối đa MAX_REWRITE_ROUNDS vòng)."""
    pass_score = config.PASS_SCORE if pass_score is None else pass_score
    rewrite_min = pass_score - (config.PASS_SCORE - config.REWRITE_MIN_SCORE)
    results: list[ScoredScript] = []
    for script in scripts:
        cards = score_script(llm, script, formula)
        item = ScoredScript(script=script, score_cards=cards, total=average(cards))
        log(f"{script.script_id}: {item.total}")
        while (rewrite_min <= item.total < pass_score
               and item.revision < config.MAX_REWRITE_ROUNDS):
            notes = [n for c in item.score_cards for n in c.improvement_notes]
            new_script = rewrite(item.script, notes)
            new_cards = score_script(llm, new_script, formula)
            candidate = ScoredScript(script=new_script, score_cards=new_cards,
                                     total=average(new_cards), revision=item.revision + 1)
            log(f"{script.script_id} viết lại lần {candidate.revision}: {candidate.total}")
            # Giữ bản tốt hơn; nếu bản mới kém hơn thì vẫn tính một vòng để không lặp vô hạn.
            item = candidate if candidate.total >= item.total else item.model_copy(update={"revision": candidate.revision})
        results.append(item)
    return results
