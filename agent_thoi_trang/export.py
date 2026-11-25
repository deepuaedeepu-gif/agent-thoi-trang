"""Ghi kết quả ra thư mục output: JSON đầy đủ + báo cáo Markdown + file prompt Veo dán vào Flow."""

from __future__ import annotations

import json
from pathlib import Path

from .models import ChannelFormula, ScoredScript


def formula_markdown(f: ChannelFormula) -> str:
    lines = ["# Công thức thành công của kênh", "", f.summary, "", "## Format thắng"]
    for w in f.winning_formats:
        lines.append(f"- **{w.name}**: {w.description} (ví dụ: {', '.join(w.example_video_ids)})")
    lines += ["", "## Mẫu hook"] + [f"- {h}" for h in f.hook_patterns]
    lines += ["", "## Nhịp và độ dài", f"- Độ dài: {f.ideal_duration_s}", f"- Nhịp cắt: {f.pacing}"]
    lines += ["", "## Phong cách", f"- Hình: {f.visual_style}", f"- Chữ: {f.text_overlay_style}", f"- Giọng: {f.voice_style}"]
    lines += ["", "## CTA"] + [f"- {c}" for c in f.cta_patterns]
    lines += ["", "## Nên"] + [f"- {d}" for d in f.do_list]
    lines += ["", "## Không nên"] + [f"- {d}" for d in f.dont_list]
    lines += ["", f"_Độ tin cậy: {f.confidence_note}_", ""]
    return "\n".join(lines)


def script_markdown(s: ScoredScript, rank: int) -> str:
    sc = s.script
    lines = [f"## {rank}. {sc.title} — {s.total} điểm", "",
             f"`{sc.script_id}` · Format: {sc.format} · Sản phẩm: {sc.product} · Viết lại: {s.revision} lần", "",
             f"**Hook:** {sc.hook}", "", "| # | Giây | Hình | Lời thoại | Chữ trên màn hình |", "|---|---|---|---|---|"]
    for scene in sc.scenes:
        lines.append(f"| {scene.index} | {scene.duration_s} | {scene.visual} | {scene.voiceover} | {scene.on_screen_text} |")
    lines += ["", f"**CTA:** {sc.cta}", f"**Caption:** {sc.caption} {' '.join(sc.hashtags)}",
              f"**Nhạc:** {sc.music_suggestion}", "", "**Điểm trung bình theo tiêu chí:**", ""]
    for i, crit in enumerate(s.score_cards[0].criteria):
        avg = sum(card.criteria[i].score for card in s.score_cards) / len(s.score_cards)
        lines.append(f"- {crit.criterion}: {avg:.1f}/{crit.max_score:g} — {crit.reason}")
    lines.append("")
    return "\n".join(lines)


def veo_prompts_text(selected: list[ScoredScript]) -> str:
    out = []
    for s in selected:
        out.append(f"===== {s.script.script_id} · {s.script.title} =====")
        for scene in s.script.scenes:
            out.append(f"--- Cảnh {scene.index} ({scene.duration_s}s) ---\n{scene.veo_prompt}\n")
    return "\n".join(out)


def write_outputs(out_dir: Path, formula: ChannelFormula, all_scored: list[ScoredScript],
                  selected: list[ScoredScript]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "formula.json").write_text(formula.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "formula.md").write_text(formula_markdown(formula), encoding="utf-8")
    (out_dir / "all_scripts_scored.json").write_text(
        json.dumps([s.model_dump() for s in all_scored], ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "selected_scripts.json").write_text(
        json.dumps([s.model_dump() for s in selected], ensure_ascii=False, indent=2), encoding="utf-8")
    md = [f"# {len(selected)} kịch bản đạt từ 90 điểm", ""]
    if not selected:
        md.append("Chưa có kịch bản nào đạt 90 điểm. Xem all_scripts_scored.json để biết góp ý.")
    md += [script_markdown(s, i + 1) for i, s in enumerate(selected)]
    (out_dir / "selected_scripts.md").write_text("\n".join(md), encoding="utf-8")
    (out_dir / "veo_prompts.txt").write_text(veo_prompts_text(selected), encoding="utf-8")
