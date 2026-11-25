"""Dòng lệnh của agent (giai đoạn 1).

    python -m agent_thoi_trang analyze  --videos inputs/videos
    python -m agent_thoi_trang formula
    python -m agent_thoi_trang scripts
    python -m agent_thoi_trang run      --videos inputs/videos   # chạy cả 3 bước
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config
from .analyze import analyze_folder
from .export import write_outputs
from .formula import build_formula
from .llm import LLM, ClaudeLLM
from .models import AnalyzedVideo, ChannelFormula, ScoredScript
from .scoring import score_and_improve, select_top
from .scripts import rewrite_script, write_scripts


def cmd_analyze(args, llm: LLM | None) -> list[AnalyzedVideo]:
    videos = analyze_folder(Path(args.videos), llm, Path(args.work), do_transcribe=not args.no_transcribe)
    print(f"Đã phân tích {len(videos)} video -> {args.work}/analyses/")
    return videos


def load_analyses(work: Path) -> list[AnalyzedVideo]:
    files = sorted((work / "analyses").glob("*.json"))
    if not files:
        raise SystemExit("Chưa có phân tích nào. Chạy lệnh 'analyze' trước.")
    return [AnalyzedVideo.model_validate_json(f.read_text(encoding="utf-8")) for f in files]


def cmd_formula(args, llm: LLM) -> ChannelFormula:
    formula = build_formula(llm, load_analyses(Path(args.work)))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "formula.json").write_text(formula.model_dump_json(indent=2), encoding="utf-8")
    print(f"Đã rút công thức kênh -> {out}/formula.json")
    return formula


def generate_until_enough(llm: LLM, formula: ChannelFormula, products: dict, presenter: dict,
                          batch_size: int, max_scripts: int) -> tuple[list[ScoredScript], list[ScoredScript]]:
    """Viết theo lô cho tới khi có đủ TARGET_COUNT kịch bản ≥ PASS_SCORE hoặc chạm max_scripts."""
    all_scored: list[ScoredScript] = []

    def rewrite(script, notes):
        return rewrite_script(llm, script, notes, formula, presenter)

    while len(all_scored) < max_scripts:
        n = min(batch_size, max_scripts - len(all_scored))
        scripts = write_scripts(llm, formula, products, presenter, n, start_index=len(all_scored) + 1)
        all_scored += score_and_improve(llm, scripts, formula, rewrite)
        selected = select_top(all_scored)
        print(f"Đã chấm {len(all_scored)} kịch bản, {len(selected)} bản đạt ≥ {config.PASS_SCORE:g}.")
        if len(selected) >= config.TARGET_COUNT:
            break
    return all_scored, select_top(all_scored)


def cmd_scripts(args, llm: LLM, formula: ChannelFormula | None = None) -> None:
    out = Path(args.out)
    if formula is None:
        formula = ChannelFormula.model_validate_json((out / "formula.json").read_text(encoding="utf-8"))
    products = config.load_yaml(args.products)
    presenter = config.load_yaml(args.presenter)
    all_scored, selected = generate_until_enough(llm, formula, products, presenter, args.batch, args.max_scripts)
    write_outputs(out, formula, all_scored, selected)
    print(f"Xong: {len(selected)} kịch bản ≥ {config.PASS_SCORE:g} -> {out}/selected_scripts.md, {out}/veo_prompts.txt")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="agent_thoi_trang", description="Agent video thời trang, giai đoạn 1")
    p.add_argument("command", choices=["analyze", "formula", "scripts", "run"])
    p.add_argument("--videos", default="inputs/videos", help="Thư mục video mẫu đã tải về")
    p.add_argument("--work", default="work", help="Thư mục trung gian")
    p.add_argument("--out", default="output", help="Thư mục kết quả")
    p.add_argument("--products", default="config/products.yaml")
    p.add_argument("--presenter", default="config/presenter.yaml")
    p.add_argument("--batch", type=int, default=10, help="Số kịch bản mỗi lô")
    p.add_argument("--max-scripts", type=int, default=40, help="Tổng số kịch bản tối đa sẽ viết")
    p.add_argument("--no-transcribe", action="store_true", help="Bỏ qua bước chép lời")
    p.add_argument("--no-ai", action="store_true", help="analyze: chỉ đo kỹ thuật bằng ffmpeg, không gọi Claude")
    args = p.parse_args(argv)

    llm = None if (args.command == "analyze" and args.no_ai) else ClaudeLLM()
    if args.command == "analyze":
        cmd_analyze(args, llm)
    elif args.command == "formula":
        cmd_formula(args, llm)
    elif args.command == "scripts":
        cmd_scripts(args, llm)
    else:
        cmd_analyze(args, llm)
        cmd_scripts(args, llm, cmd_formula(args, llm))


if __name__ == "__main__":
    main()
