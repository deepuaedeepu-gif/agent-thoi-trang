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

from agent_thoi_trang import consent, facebook_scan, settings, tts  # noqa: E402
from agent_thoi_trang.analyze import analyze_folder  # noqa: E402
from agent_thoi_trang.export import formula_markdown, script_markdown, write_outputs  # noqa: E402
from agent_thoi_trang.formula import build_formula  # noqa: E402
from agent_thoi_trang import llm as llm_mod  # noqa: E402
from agent_thoi_trang.pipeline import ScriptJob, generate_until_enough  # noqa: E402
from agent_thoi_trang.models import ScoredScript  # noqa: E402
from agent_thoi_trang.production import get_status, produce, set_status  # noqa: E402
from agent_thoi_trang.store import Consent, Presenter, Product, SavedFormula, Store, Voice, now, slugify  # noqa: E402

st.set_page_config(page_title="Agent video thời trang", page_icon="🎬", layout="wide")
store = Store()
settings.apply()


@st.cache_resource
def ensure_ffmpeg() -> str | None:
    """Máy chưa có ffmpeg (thường gặp trên Windows/Mac) thì tải bản đóng gói sẵn ở lần chạy đầu."""
    import shutil

    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return None
    try:
        import static_ffmpeg

        static_ffmpeg.add_paths()
        return None
    except Exception as exc:  # noqa: BLE001
        return f"Không tìm thấy ffmpeg và không tải được tự động: {exc}. Hãy cài ffmpeg rồi mở lại app."


_ffmpeg_error = ensure_ffmpeg()
if _ffmpeg_error:
    st.error(_ffmpeg_error)


def llm_ready() -> tuple[bool, str]:
    if os.environ.get("LLM_BACKEND", "claude_code") == "api":
        return bool(os.environ.get("ANTHROPIC_API_KEY")), "Claude qua khoá API"
    return bool(llm_mod.claude_code_path()), "Claude qua Claude Code (gói Pro/Max)"


# ---------- Thanh bên: trạng thái ----------

with st.sidebar:
    st.header("Trạng thái")
    _ok, _label = llm_ready()
    st.write(f"{'✅' if _ok else '⚠️'} {_label}")
    for spec in settings.KEYS:
        if spec.env == "ANTHROPIC_API_KEY":
            continue
        st.write(f"{'✅' if os.environ.get(spec.env) else '▫️'} {spec.label}")
    st.caption("Cài đặt ở tab ⚙️ Cài đặt.")
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


def need_llm():
    ok, label = llm_ready()
    if not ok:
        st.error(f"Chưa dùng được {label}. Xem hướng dẫn ở tab ⚙️ Cài đặt.")
        return None
    return llm_mod.make_llm()


tab_formula, tab_models, tab_voices, tab_build, tab_settings = st.tabs(
    ["📈 Công thức thành công", "🧍 Kho Người mẫu", "🎙️ Kho voice", "🎬 Dựng video", "⚙️ Cài đặt"])


# ---------- Tab Cài đặt ----------

with tab_settings:
    st.subheader("Kết nối Claude")
    saved_all = settings.load()
    backend_labels = {"claude_code": "Claude Code (dùng gói Pro/Max của bạn)", "api": "Khoá API Anthropic (trả theo lượng dùng)"}
    current_backend = os.environ.get("LLM_BACKEND", "claude_code")
    choice = st.radio("Agent gọi Claude qua", list(backend_labels), format_func=backend_labels.get,
                      index=list(backend_labels).index(current_backend), horizontal=True)
    if choice != current_backend:
        settings.save({**saved_all, "LLM_BACKEND": choice})
        st.rerun()
    if choice == "claude_code":
        found = llm_mod.claude_code_path()
        if found:
            st.success(f"Đã tìm thấy Claude Code: {found}")
        else:
            st.warning("Chưa tìm thấy Claude Code trên máy.")
        with st.expander("Cách cài và đăng nhập Claude Code", expanded=not found):
            st.markdown(settings.CLAUDE_CODE_GUIDE)
        if found and st.button("Kiểm tra kết nối"):
            from pydantic import BaseModel

            class Ping(BaseModel):
                reply: str

            with st.spinner("Đang hỏi Claude Code..."):
                try:
                    r = llm_mod.ClaudeCodeLLM(timeout=180).parse(
                        "Trả lời ngắn bằng tiếng Việt.", [llm_mod.text_block("Chào bạn, trả lời 'Đã kết nối'.")], Ping)
                    st.success(f"Claude Code trả lời: {r.reply}")
                except Exception as exc:
                    st.error(str(exc))
    st.divider()
    st.subheader("Khoá API")
    st.caption("Khoá được lưu trong file data/settings.json trên máy bạn, không gửi đi đâu ngoài nhà cung cấp "
               "tương ứng. Mỗi khoá chỉ cần khi dùng chức năng tương ứng.")
    saved = settings.load()
    with st.form("api-keys"):
        values = {}
        for spec in settings.KEYS:
            tag = "bắt buộc" if spec.required else "tuỳ chọn"
            current = os.environ.get(spec.env, "")
            st.markdown(f"#### {spec.label} · {tag}")
            st.caption(spec.used_for + (f" · Hiện tại: {settings.mask(current)}" if current else " · Chưa nhập"))
            with st.expander("Cách tạo khoá"):
                st.markdown(spec.guide)
            values[spec.env] = st.text_input(spec.label, value=saved.get(spec.env, ""), type="password",
                                             key=f"set-{spec.env}", label_visibility="collapsed",
                                             placeholder="Dán khoá vào đây")
        if st.form_submit_button("Lưu cài đặt", type="primary"):
            settings.save({"LLM_BACKEND": os.environ.get("LLM_BACKEND", "claude_code"), **values})
            st.success("Đã lưu.")
            st.rerun()


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
    llm = llm_mod.make_llm()
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

def save_upload(upload, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(upload.getvalue())
    return dest


def consent_box(kind: str, purpose: str, extra: str = "") -> consent.Challenge | None:
    """Tạo/giữ câu đồng ý có mã ngẫu nhiên cho một biểu mẫu."""
    state_key = f"challenge-{kind}"
    person = st.text_input("Họ tên người thật", key=f"name-{kind}")
    if st.button("Tạo câu đồng ý mới", key=f"mk-{kind}") and person.strip():
        st.session_state[state_key] = consent.new_challenge(person, purpose)
    ch = st.session_state.get(state_key)
    if ch:
        st.markdown("**Người đó tự quay/ghi âm, đọc đúng câu sau** (mã đổi mỗi lần bấm tạo):")
        st.info(ch.statement)
        if extra:
            st.caption(extra)
    return ch


with tab_models:
    st.subheader("Người dẫn")
    for p in store.presenters():
        cols = st.columns([1, 3, 1])
        with cols[0]:
            if p.images:
                st.image(p.images[0], width=120)
        with cols[1]:
            badge = "Nhân vật AI" if p.kind == "ai_original" else (
                "Người thật · đã xác minh" if p.usable else "Người thật · CHƯA xác minh")
            st.markdown(f"**{p.name}** · {badge}")
            st.caption(p.description_en)
        with cols[2]:
            if p.id != "may-ai" and st.button("Xoá", key=f"delp-{p.id}"):
                store.delete_presenter(p.id)
                st.rerun()
    st.divider()
    kind = st.radio("Thêm người dẫn", ["Nhân vật AI mới", "Người thật (cần xác minh đồng ý)"], horizontal=True)
    if kind == "Nhân vật AI mới":
        st.caption("Nhân vật AI phải là người hư cấu, không mô tả hay dùng ảnh của người thật nào.")
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
    else:
        st.caption("Chỉ dùng mặt của chính bạn hoặc người đã đồng ý. Ảnh tham chiếu được lấy từ chính video "
                   "xác minh, nên không nhận ảnh từ nguồn khác.")
        ch = consent_box("presenter", "khuôn mặt và giọng nói",
                         "Quay dọc 20-40 giây, nơi đủ sáng: nhìn thẳng camera đọc câu trên, sau đó quay mặt sang "
                         "trái, sang phải, rồi lùi ra xa cho thấy toàn thân.")
        if ch:
            vid = st.file_uploader("Video xác minh", type=["mp4", "mov", "m4v", "webm"], key="consent-video")
            pdesc = st.text_area("Mô tả ngoại hình bằng tiếng Anh (tóc, dáng, phong cách; không cần tên)",
                                 key="real-desc")
            if st.button("Xác minh và lưu", type="primary", key="verify-presenter") and vid:
                pid = slugify(ch.person_name)
                vpath = save_upload(vid, store.root / "presenters" / pid / f"consent{Path(vid.name).suffix}")
                with st.spinner("Đang nghe lại video để kiểm tra câu đồng ý..."):
                    try:
                        result = consent.verify_media(vpath, ch)
                    except Exception as exc:
                        result = None
                        st.error(f"Không xác minh được: {exc}")
                if result and result.passed:
                    frames = consent.extract_reference_frames(vpath, store.root / "presenters" / pid)
                    store.save_presenter(Presenter(
                        id=pid, name=ch.person_name, kind="real_person", images=frames, created_at=now(),
                        description_en=pdesc or "The real person shown in the reference images.",
                        consent=Consent(person_name=ch.person_name, consent_video=str(vpath), statement=ch.statement,
                                        verified=True, verified_at=now())))
                    st.session_state.pop("challenge-presenter", None)
                    st.success(f"Đã xác minh và lưu {ch.person_name} với {len(frames)} ảnh tham chiếu lấy từ video.")
                elif result:
                    st.error("Chưa đạt: " + "; ".join(result.reasons))
                    st.caption(f"App nghe được: “{result.transcript}”")


# ---------- Tab Kho voice ----------

with tab_voices:
    st.subheader("Kho giọng")
    voices_now = store.voices()
    st.dataframe([{"Tên": v.name, "Nhà cung cấp": v.provider, "Mã giọng": v.provider_voice_id,
                   "Loại": "Giọng tạo mới" if v.kind == "cloned" else "Có sẵn", "Giới tính": v.gender}
                  for v in voices_now], width="stretch", hide_index=True)
    c1, c2, c3 = st.columns(3)
    if c1.button("Thêm giọng FPT.AI"):
        for v in tts.fpt_stock_voices():
            store.save_voice(v)
        st.rerun()
    if c2.button("Cập nhật giọng Google"):
        try:
            for v in tts.google_voices():
                store.save_voice(v)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if c3.button("Thêm giọng ElevenLabs"):
        try:
            for v in tts.elevenlabs_voices():
                store.save_voice(v)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.markdown("**Nghe thử**")
    pv = st.selectbox("Giọng", voices_now, format_func=lambda v: v.name, key="preview-voice")
    ptext = st.text_input("Câu thử", "Xin chào mấy bà, hôm nay mình phối đồ đi chơi Tết nha!")
    if st.button("Nghe thử") and pv:
        try:
            out = tts.synthesize(pv, ptext, store.root / "voices" / "_preview.mp3")
            st.audio(out.read_bytes(), format="audio/mp3")
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Tạo giọng mới từ file ghi âm (ElevenLabs)")
    st.caption("Chỉ tạo giọng của chính bạn hoặc người đã đồng ý. File tải lên phải mở đầu bằng câu đồng ý "
               "do chính giọng đó đọc; cả file được dùng làm mẫu giọng.")
    ch = consent_box("voice", "giọng nói",
                     "Ghi âm 30-90 giây nơi yên tĩnh: đọc câu trên, sau đó đọc tiếp đoạn sau để làm mẫu giọng: "
                     + consent.SAMPLE_PARAGRAPH)
    if ch:
        audio = st.file_uploader("File ghi âm (mp3, wav, m4a)", type=["mp3", "wav", "m4a"], key="consent-audio")
        if st.button("Xác minh và tạo giọng", type="primary") and audio:
            vid = f"clone-{slugify(ch.person_name)}"
            apath = save_upload(audio, store.root / "voices" / vid / f"sample{Path(audio.name).suffix}")
            with st.spinner("Đang nghe lại để kiểm tra câu đồng ý..."):
                try:
                    result = consent.verify_media(apath, ch)
                except Exception as exc:
                    result = None
                    st.error(f"Không xác minh được: {exc}")
            if result and result.passed:
                voice = Voice(id=vid, name=f"{ch.person_name} (giọng tạo mới)", provider="elevenlabs",
                              provider_voice_id="", kind="cloned", sample=str(apath), created_at=now(),
                              consent=Consent(person_name=ch.person_name, consent_audio=str(apath),
                                              statement=ch.statement, verified=True, verified_at=now()))
                try:
                    voice.provider_voice_id = tts.clone_elevenlabs(voice, apath)
                    store.save_voice(voice)
                    st.session_state.pop("challenge-voice", None)
                    st.success(f"Đã tạo giọng {voice.name}.")
                except Exception as exc:
                    st.error(f"Xác minh đạt nhưng ElevenLabs chưa tạo được giọng: {exc}")
            elif result:
                st.error("Chưa đạt: " + "; ".join(result.reasons))
                st.caption(f"App nghe được: “{result.transcript}”")


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


def draft_zip(folder: Path) -> bytes:
    """Bản nháp chỉnh sửa được: clip rời, voice, phụ đề, timeline, bản xem thử."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in folder.rglob("*"):
            if f.is_file() and "scenes" not in f.parts:
                z.write(f, f.relative_to(folder))
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
                        all_scored, selected = generate_until_enough(llm_mod.make_llm(), job, log=box.write)
                        write_outputs(job_dir, formula.formula, all_scored, selected)
                        st.session_state["last_job"] = {"dir": str(job_dir), "images": product.images,
                                                        "presenter_id": presenter.id, "voice_id": voice.id,
                                                        "selected": [s.model_dump() for s in selected]}
                        box.update(label=f"Xong: {len(selected)}/{target} kịch bản đạt ≥ {threshold}",
                                   state="complete")
                    except Exception as exc:
                        box.update(label=f"Lỗi: {exc}", state="error")

    last = st.session_state.get("last_job")
    if last:
        st.divider()
        selected = [ScoredScript.model_validate(s) for s in last["selected"]]
        job_dir = Path(last["dir"])
        st.subheader(f"{len(selected)} kịch bản tốt nhất")
        for i, s in enumerate(selected):
            with st.expander(f"{i + 1}. {s.script.title} — {s.total} điểm"):
                st.markdown(script_markdown(s, i + 1))

        st.subheader("Tạo video")
        platform = st.radio("Nền tảng", ["Gemini Omni Flash (API Google)", "Grok Imagine (API xAI)",
                                         "Google Flow (xuất prompt, dán tay)"], horizontal=True)
        if platform.startswith("Google Flow"):
            st.caption("Google Flow không có API. Tải gói prompt và ảnh sản phẩm để dán vào Flow.")
            st.download_button("Tải gói cho Google Flow (.zip)", flow_package(job_dir, last["images"]),
                               file_name=f"flow_{job_dir.name}.zip")
        else:
            provider = "omni" if platform.startswith("Gemini") else "grok"
            presenter_obj = next((p for p in store.presenters() if p.id == last["presenter_id"]), None)
            voice_obj = next((v for v in store.voices() if v.id == last["voice_id"]), None)
            st.caption(f"Người dẫn: {presenter_obj.name if presenter_obj else '?'} · Voice: "
                       f"{voice_obj.name if voice_obj else '?'} · Ảnh sản phẩm: {len(last['images'])}. "
                       "Mỗi cảnh luôn gửi kèm ảnh người dẫn và ảnh sản phẩm làm ảnh tham chiếu.")
            if presenter_obj and not presenter_obj.images:
                st.warning("Người dẫn này chưa có ảnh; nền tảng chỉ dựa vào mô tả nên nhân vật có thể không "
                           "đồng nhất giữa các cảnh. Nên thêm ảnh ở Kho Người mẫu.")
            n_scenes = sum(len(s.script.scenes) for s in selected)
            st.caption(f"Sẽ tạo {n_scenes} clip cho {len(selected)} video. Nền tảng tính phí theo từng clip.")
            if st.button("Tạo video", type="primary"):
                if not (presenter_obj and voice_obj):
                    st.error("Không tìm thấy người dẫn hoặc voice đã chọn.")
                else:
                    with st.status("Đang tạo video...", expanded=True) as box:
                        done = 0
                        for s in selected:
                            try:
                                produce(s, presenter_obj, voice_obj, last["images"], provider,
                                        job_dir / "videos", log=box.write)
                                done += 1
                            except Exception as exc:
                                box.write(f"❌ {s.script.script_id}: {exc}")
                        box.update(label=f"Xong {done}/{len(selected)} video", state="complete" if done else "error")

        videos_dir = job_dir / "videos"
        if videos_dir.exists():
            st.subheader("Duyệt video")
            for folder in sorted(p for p in videos_dir.iterdir() if (p / "preview.mp4").exists()):
                status = get_status(folder)
                with st.expander(f"{folder.name} · {status['status']}", expanded=status["status"] == "chờ duyệt"):
                    st.video(str(folder / "preview.mp4"))
                    note = st.text_input("Ghi chú", status.get("note", ""), key=f"note-{folder.name}")
                    a, b, c = st.columns(3)
                    if a.button("Duyệt", key=f"ok-{folder.name}"):
                        set_status(folder, "đã duyệt", note)
                        st.rerun()
                    if b.button("Cần sửa", key=f"fix-{folder.name}"):
                        set_status(folder, "cần sửa", note)
                        st.rerun()
                    c.download_button("Tải bản nháp (.zip)", draft_zip(folder), file_name=f"{folder.name}_ban_nhap.zip",
                                      key=f"dl-{folder.name}")
