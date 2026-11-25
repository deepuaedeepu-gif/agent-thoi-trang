"""App điều khiển agent video thời trang.

Chạy:  streamlit run app/app.py
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from agent_thoi_trang import config, facebook_scan  # noqa: E402
from agent_thoi_trang.analyze import analyze_folder  # noqa: E402
from agent_thoi_trang.export import formula_markdown, script_markdown, write_outputs  # noqa: E402
from agent_thoi_trang.formula import build_formula  # noqa: E402
from agent_thoi_trang.llm import ClaudeLLM  # noqa: E402
from agent_thoi_trang.pipeline import ScriptJob, generate_until_enough  # noqa: E402
from agent_thoi_trang.store import Presenter, Product, SavedFormula, Store, now, slugify  # noqa: E402

st.set_page_config(page_title="Agent video thời trang", page_icon="🎬", layout="wide")
store = Store()


# ---------- Thanh bên: khoá API ----------

with st.sidebar:
    st.header("Kết nối")
    key = st.text_input("Anthropic API key", type="password", value=os.environ.get("ANTHROPIC_API_KEY", ""),
                        help="Chỉ giữ trong phiên chạy này, không ghi ra file.")
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
    st.caption("Tạo video tự động (Veo qua Gemini API, Grok Imagine qua xAI API) sẽ có ở bước tiếp theo.")
    st.divider()
    st.subheader("Facebook")
    if facebook_scan.has_session():
        st.success("Đã có phiên đăng nhập trong cửa sổ riêng.")
    else:
        st.info("Chưa đăng nhập.")
    if st.button("Đăng nhập Facebook", help="Mở cửa sổ trình duyệt riêng. Bạn tự đăng nhập, app không lưu mật khẩu."):
        subprocess.Popen([sys.executable, "-m", "agent_thoi_trang.facebook_scan", "login"], cwd=ROOT)
        st.toast("Đã mở cửa sổ đăng nhập. Đăng nhập xong thì đóng cửa sổ đó.")
    st.caption("Điều khoản của Meta không cho phép thu thập tự động; tài khoản quét có thể bị yêu cầu "
               "xác minh hoặc khoá tạm thời. App quét chậm và giới hạn số video để giảm rủi ro.")


def need_llm() -> ClaudeLLM | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("Cần nhập Anthropic API key ở thanh bên trái.")
        return None
    return ClaudeLLM()


tab_formula, tab_models, tab_voices, tab_build = st.tabs(
    ["📈 Công thức thành công", "🧍 Kho Người mẫu", "🎙️ Kho voice", "🎬 Dựng video"])


# ---------- Tab Công thức thành công ----------

def run_scan(urls: list[str], out_dir: Path, top_n: int, box) -> None:
    cmd = [sys.executable, "-m", "agent_thoi_trang.facebook_scan", "scan", "--out", str(out_dir),
           "--top", str(top_n), *urls]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        box.write(line.rstrip())
    if proc.wait() != 0:
        raise RuntimeError("Quét Facebook thất bại, xem nhật ký ở trên.")


def analyze_and_save(name: str, sources: list[str], video_dir: Path, box) -> SavedFormula:
    llm = ClaudeLLM()
    box.write("Đang phân tích từng video (khung hình, nhịp cắt, lời thoại)...")
    videos = analyze_folder(video_dir, llm, video_dir.parent / "work")
    if not videos:
        raise RuntimeError("Không có video nào để phân tích.")
    box.write(f"Đã phân tích {len(videos)} video. Đang rút công thức...")
    formula = build_formula(llm, videos)
    saved = SavedFormula(id=slugify(name), name=name, sources=sources, created_at=now(),
                         video_count=len(videos), formula=formula, videos=videos)
    store.save_formula(saved)
    return saved


with tab_formula:
    st.subheader("Tạo công thức mới")
    name = st.text_input("Tên công thức", placeholder="Ví dụ: Kênh jeans A - try-on")
    mode = st.radio("Nguồn video", ["Quét link Facebook", "Tải video lên"], horizontal=True)
    if mode == "Quét link Facebook":
        links = st.text_area("Link trang hoặc link reel (mỗi dòng một link)", height=100,
                             placeholder="https://www.facebook.com/profile.php?id=...")
        top_n = st.slider("Số video tốt nhất cần chọn", 5, 20, 20)
        go = st.button("Quét và tìm công thức", type="primary")
        if go:
            urls = [u.strip() for u in links.splitlines() if u.strip()]
            if not name or not urls:
                st.error("Cần tên công thức và ít nhất 1 link.")
            elif not facebook_scan.has_session():
                st.error("Hãy bấm 'Đăng nhập Facebook' ở thanh bên trước.")
            elif need_llm():
                job = store.new_job_dir()
                with st.status("Đang chạy...", expanded=True) as box:
                    try:
                        run_scan(urls, job / "videos", top_n, box)
                        saved = analyze_and_save(name, urls, job / "videos", box)
                        box.update(label=f"Đã lưu công thức '{saved.name}' từ {saved.video_count} video",
                                   state="complete")
                    except Exception as exc:
                        box.update(label=f"Lỗi: {exc}", state="error")
    else:
        files = st.file_uploader("Video mẫu (mp4, mov)", type=["mp4", "mov", "m4v", "webm"], accept_multiple_files=True)
        meta = st.file_uploader("metadata.csv (tuỳ chọn: video_id,caption,views,likes,comments,shares)", type=["csv"])
        if st.button("Phân tích và tìm công thức", type="primary"):
            if not name or not files:
                st.error("Cần tên công thức và ít nhất 1 video.")
            elif need_llm():
                job = store.new_job_dir()
                vdir = job / "videos"
                vdir.mkdir(parents=True)
                for f in files:
                    (vdir / Path(f.name).name).write_bytes(f.getvalue())
                if meta:
                    (vdir / "metadata.csv").write_bytes(meta.getvalue())
                with st.status("Đang chạy...", expanded=True) as box:
                    try:
                        saved = analyze_and_save(name, [f.name for f in files], vdir, box)
                        box.update(label=f"Đã lưu công thức '{saved.name}'", state="complete")
                    except Exception as exc:
                        box.update(label=f"Lỗi: {exc}", state="error")

    st.divider()
    st.subheader("Công thức đã lưu")
    saved_list = store.formulas()
    if not saved_list:
        st.caption("Chưa có công thức nào.")
    for f in saved_list:
        with st.expander(f"{f.name} · {f.video_count} video · {f.created_at}"):
            st.markdown(formula_markdown(f.formula))
            st.caption("Nguồn: " + ", ".join(f.sources))
            if st.button("Xoá", key=f"del-{f.id}"):
                store.delete_formula(f.id)
                st.rerun()


# ---------- Tab Kho Người mẫu ----------

with tab_models:
    st.subheader("Người dẫn")
    for p in store.presenters():
        cols = st.columns([1, 3])
        with cols[0]:
            if p.images:
                st.image(p.images[0], width=140)
        with cols[1]:
            badge = "Nhân vật AI" if p.kind == "ai_original" else (
                "Người thật · đã xác minh" if p.usable else "Người thật · CHƯA xác minh")
            st.markdown(f"**{p.name}** · {badge}")
            st.caption(p.description_en)
    st.divider()
    st.subheader("Tạo nhân vật AI mới")
    st.caption("Nhân vật AI phải là người hư cấu, không mô tả theo người thật nào.")
    with st.form("new-ai-presenter", clear_on_submit=True):
        pname = st.text_input("Tên nhân vật")
        pdesc = st.text_area("Mô tả ngoại hình (tiếng Anh, dùng cho prompt video)",
                             placeholder="A fictional Vietnamese woman in her late 20s, long straight black hair...")
        pimgs = st.file_uploader("Ảnh nhân vật do AI tạo: mặt, các góc, toàn thân (tuỳ chọn)",
                                 type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
        if st.form_submit_button("Lưu nhân vật"):
            if not pname or not pdesc:
                st.error("Cần tên và mô tả.")
            else:
                pid = slugify(pname)
                paths = [store.save_file("presenters", pid, f.name, f.getvalue()) for f in pimgs or []]
                store.save_presenter(Presenter(id=pid, name=pname, kind="ai_original", description_en=pdesc,
                                               images=paths, created_at=now()))
                st.success(f"Đã lưu {pname}.")
                st.rerun()
    st.info("Thêm người dẫn là người thật (cần video tự quay nói câu đồng ý để xác minh) sẽ có ở bước tiếp theo.")


# ---------- Tab Kho voice ----------

with tab_voices:
    st.subheader("Giọng đọc có sẵn")
    st.dataframe([{"Tên": v.name, "Nhà cung cấp": v.provider, "Mã giọng": v.provider_voice_id,
                   "Giới tính": v.gender} for v in store.voices()], width="stretch", hide_index=True)
    st.info("Thêm giọng FPT.AI, ElevenLabs, nghe thử, và tạo giọng mới từ mp3 (cần bản ghi đồng ý bằng chính "
            "giọng đó) sẽ có ở bước tiếp theo.")


# ---------- Tab Dựng video ----------

def flow_package(job_dir: Path, image_paths: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for fname in ("veo_prompts.txt", "selected_scripts.md"):
            if (job_dir / fname).exists():
                z.write(job_dir / fname, fname)
        for p in image_paths:
            z.write(p, f"anh_san_pham/{Path(p).name}")
    return buf.getvalue()


with tab_build:
    formulas = store.formulas()
    presenters = [p for p in store.presenters() if p.usable]
    voices = [v for v in store.voices() if v.usable]
    if not formulas:
        st.warning("Chưa có công thức nào. Hãy tạo ở tab Công thức thành công.")
    else:
        c1, c2, c3 = st.columns(3)
        formula = c1.selectbox("Công thức thành công", formulas, format_func=lambda f: f.name)
        presenter = c2.selectbox("Người dẫn", presenters, format_func=lambda p: p.name)
        voice = c3.selectbox("Voice", voices, format_func=lambda v: v.name)

        st.markdown("**Sản phẩm**")
        pc1, pc2 = st.columns([2, 1])
        prod_name = pc1.text_input("Tên sản phẩm")
        prod_price = pc2.text_input("Giá")
        prod_details = st.text_area("Chất liệu, màu, size, chi tiết", height=70)
        prod_points = st.text_input("Điểm bán hàng (cách nhau bằng dấu phẩy)")
        prod_imgs = st.file_uploader("Ảnh sản phẩm", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
        audience = st.text_input("Khách hàng mục tiêu / dịp (tuỳ chọn)", placeholder="Nữ 18-30, đi chơi Tết")

        s1, s2, s3 = st.columns(3)
        target = s1.number_input("Số kịch bản muốn có", 1, 20, 10)
        threshold = s2.slider("Ngưỡng điểm", 70, 100, 90)
        max_scripts = s3.number_input("Viết tối đa (để giới hạn chi phí)", int(target), 100, int(target) * 4)

        if st.button("Tạo kịch bản", type="primary"):
            if not prod_name or not prod_imgs:
                st.error("Cần tên sản phẩm và ít nhất 1 ảnh sản phẩm.")
            elif need_llm():
                product = Product(id=slugify(prod_name), name=prod_name, price=prod_price, details=prod_details,
                                  selling_points=[s.strip() for s in prod_points.split(",") if s.strip()],
                                  created_at=now())
                product.images = [store.save_file("products", product.id, f.name, f.getvalue()) for f in prod_imgs]
                store.save_product(product)
                job_dir = store.new_job_dir()
                job = ScriptJob(
                    formula=formula.formula,
                    products={"products": [product.model_dump(exclude={"id", "images", "created_at"})],
                              "audience": audience},
                    presenter=presenter.as_presenter_cfg(),
                    voice=voice.model_dump(include={"name", "provider", "provider_voice_id", "gender"}),
                    target_count=int(target), pass_score=float(threshold),
                    batch_size=min(10, int(target) * 2), max_scripts=int(max_scripts),
                    product_images=product.images,
                )
                with st.status("Agent đang viết và chấm kịch bản...", expanded=True) as box:
                    try:
                        all_scored, selected = generate_until_enough(ClaudeLLM(), job, log=box.write)
                        write_outputs(job_dir, formula.formula, all_scored, selected)
                        st.session_state["last_job"] = {"dir": str(job_dir), "images": product.images,
                                                        "selected": [s.model_dump() for s in selected]}
                        box.update(label=f"Xong: {len(selected)}/{target} kịch bản đạt ≥ {threshold}",
                                   state="complete")
                    except Exception as exc:
                        box.update(label=f"Lỗi: {exc}", state="error")

    last = st.session_state.get("last_job")
    if last:
        from agent_thoi_trang.models import ScoredScript

        st.divider()
        selected = [ScoredScript.model_validate(s) for s in last["selected"]]
        st.subheader(f"{len(selected)} kịch bản tốt nhất")
        for i, s in enumerate(selected):
            with st.expander(f"{i + 1}. {s.script.title} — {s.total} điểm"):
                st.markdown(script_markdown(s, i + 1))
        job_dir = Path(last["dir"])

        st.subheader("Tạo video")
        platform = st.radio("Nền tảng", ["Google Flow (xuất prompt, dán tay)", "Veo (API)", "Grok Imagine (API)"],
                            horizontal=True)
        if platform.startswith("Google Flow"):
            st.caption("Google Flow không có API. Tải gói prompt và ảnh sản phẩm để dán vào Flow.")
            st.download_button("Tải gói cho Google Flow (.zip)", flow_package(job_dir, last["images"]),
                               file_name=f"flow_{job_dir.name}.zip")
        else:
            st.info("Tự động tạo video qua API sẽ có ở bước tiếp theo. Agent sẽ luôn gửi kèm ảnh người dẫn, "
                    "ảnh sản phẩm và voice đã chọn cho từng cảnh.")
