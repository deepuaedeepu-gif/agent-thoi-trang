"""Điều phối tạo kịch bản: dùng chung cho dòng lệnh và app."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .llm import LLM
from .models import ChannelFormula, ScoredScript
from .scoring import score_and_improve, select_top
from .scripts import rewrite_script, write_scripts


@dataclass
class ScriptJob:
    formula: ChannelFormula
    products: dict
    presenter: dict
    target_count: int = config.TARGET_COUNT
    pass_score: float = config.PASS_SCORE
    batch_size: int = 10
    max_scripts: int = 40
    product_images: Sequence[str | Path] = field(default_factory=tuple)
    voice: dict | None = None


def generate_until_enough(llm: LLM, job: ScriptJob,
                          log: Callable[[str], None] = print) -> tuple[list[ScoredScript], list[ScoredScript]]:
    """Viết theo lô cho tới khi có đủ `target_count` kịch bản ≥ `pass_score` hoặc chạm `max_scripts`."""
    all_scored: list[ScoredScript] = []

    def rewrite(script, notes):
        return rewrite_script(llm, script, notes, job.formula, job.presenter)

    def pick():
        return select_top(all_scored, target=job.target_count, pass_score=job.pass_score)

    while len(all_scored) < job.max_scripts:
        n = min(job.batch_size, job.max_scripts - len(all_scored))
        log(f"Đang viết {n} kịch bản mới...")
        scripts = write_scripts(llm, job.formula, job.products, job.presenter, n,
                                start_index=len(all_scored) + 1,
                                product_images=job.product_images, voice=job.voice)
        all_scored += score_and_improve(llm, scripts, job.formula, rewrite, log=log, pass_score=job.pass_score)
        log(f"Đã chấm {len(all_scored)} kịch bản, {len(pick())} bản đạt ≥ {job.pass_score:g}.")
        if len(pick()) >= job.target_count:
            break
    return all_scored, pick()
