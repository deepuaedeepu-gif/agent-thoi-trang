# Agent video thời trang

## Chạy nhanh

1. Cài [Python 3.11 trở lên](https://www.python.org/downloads/) (Windows: tick **Add python.exe to PATH**).
2. Tải code về và giải nén.
3. Bấm đúp **`chay_app_windows.bat`** (Windows) hoặc **`chay_app_mac.command`** (macOS; lần đầu chuột phải → Open).
   Lần đầu mất vài phút để cài thư viện.
4. Trình duyệt mở **http://localhost:8501**. Vào tab **⚙️ Cài đặt**, làm theo hướng dẫn để tạo và dán khoá API.
   Chỉ khoá Claude là bắt buộc để tạo kịch bản.


## App điều khiển

```bash
pip install -r requirements.txt
python -m playwright install chromium     # cho chức năng quét Facebook
streamlit run app/app.py                  # mở http://localhost:8501
```

| Tab | Chức năng |
|---|---|
| Công thức thành công | Đăng nhập Facebook trong cửa sổ riêng, quét link trang/reel, chọn 5-20 reel nhiều view nhất, tải về, phân tích, lưu công thức có tên. Hoặc tải video lên trực tiếp. |
| Kho Người mẫu | Nhân vật AI (mô tả + ảnh). Người thật: bắt buộc video tự quay đọc câu đồng ý có mã ngẫu nhiên; ảnh tham chiếu lấy từ chính video đó. |
| Kho voice | Giọng có sẵn Google Cloud TTS, FPT.AI, ElevenLabs; nghe thử; tạo giọng mới từ file ghi âm (ElevenLabs) khi file mở đầu bằng câu đồng ý có mã ngẫu nhiên. |
| Dựng video | Chọn công thức, người dẫn, voice, ảnh sản phẩm, số kịch bản, ngưỡng điểm → tạo kịch bản → tạo video qua Gemini Omni Flash hoặc Grok Imagine (luôn gửi kèm ảnh người dẫn + ảnh sản phẩm) → ghép voice, chữ → duyệt → tải bản nháp. |

Khoá API nhập ở thanh bên (chỉ giữ trong phiên chạy) hoặc đặt biến môi trường: `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`, `XAI_API_KEY`, `GOOGLE_TTS_API_KEY`, `FPT_AI_API_KEY`, `ELEVENLABS_API_KEY`.

**Bản nháp mỗi video** (`data/jobs/<lần chạy>/videos/<mã kịch bản>/`): `clips/` clip từng cảnh, `voice/` lời đọc
từng cảnh, `subtitles.srt`, `text_overlays.srt`, `timeline.json` (mốc thời gian, file, chữ, prompt từng cảnh),
`preview.mp4`. Kéo các file này vào CapCut hoặc Premiere để chỉnh.

**Về nền tảng tạo video:** Veo 3.1 bản preview trên Gemini API đã ngừng ngày 22/10/2026; Google thay bằng
Gemini Omni Flash (`gemini-omni-1.1-flash`), app dùng model này. Omni không nhận ảnh của một số người nổi tiếng
và ghi rõ chỉ kiểm thử đầy đủ với tiếng Anh, nên lời thoại tiếng Việt được tạo riêng bằng TTS rồi ghép vào.

**Về xác minh đồng ý:** cần `faster-whisper` (tải model lần đầu). Câu đồng ý chứa mã 4 số đổi mỗi lần, nên video
hay âm thanh tải từ mạng về không qua được bước này.

Lưu ý về quét Facebook: bạn tự đăng nhập trong cửa sổ trình duyệt riêng (hồ sơ ở `data/browser/facebook`),
app không lưu mật khẩu. Điều khoản của Meta không cho phép thu thập tự động, nên tài khoản dùng để quét có thể
bị yêu cầu xác minh hoặc khoá tạm thời. App cuộn chậm, nghỉ ngẫu nhiên và giới hạn 20 video để giảm rủi ro.

Dữ liệu (công thức, người dẫn, voice, sản phẩm, kết quả) lưu trong thư mục `data/` trên máy bạn.

Google Flow và muse.ai không có API tạo video chính thức, nên app chỉ xuất prompt để dán tay.

## Dòng lệnh (giai đoạn 1)

Agent phân tích video mẫu của các kênh thời trang, rút ra công thức thành công, viết kịch bản,
chấm điểm và chọn **10 kịch bản đạt từ 90 điểm**, mỗi kịch bản kèm **prompt Veo cho từng cảnh**
để dán vào Google Flow.

Giai đoạn 2 (tự tạo video bằng Veo API + giọng đọc) và giai đoạn 3 (trang duyệt, xuất CapCut draft /
FCPXML) sẽ làm sau.

## Nguyên tắc

- Agent chỉ học **phong cách** của kênh mẫu: hook, format, nhịp cắt, chữ, CTA, độ dài.
- Agent **không** sao chép khuôn mặt, giọng nói hay ngữ điệu của người trong video mẫu.
  Người dẫn mặc định là nhân vật AI mới trong `config/presenter.yaml`. Chế độ `owner` (mặt và giọng
  của chủ kênh) chỉ bật được sau khi xác minh danh tính (`owner.verified: true`).

## Cài đặt

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# cần ffmpeg: apt install ffmpeg  (macOS: brew install ffmpeg)
export ANTHROPIC_API_KEY=...        # hoặc: ant auth login
```

## Chuẩn bị dữ liệu

Facebook chặn đọc tự động, nên hãy tải video mẫu về:

```
inputs/videos/
  reel_01.mp4
  reel_02.mp4
  metadata.csv      # tuỳ chọn nhưng nên có, để biết video nào thắng
```

`metadata.csv`:

```csv
video_id,caption,views,likes,comments,shares
reel_01,"Jeans ống loe hack dáng",120000,5400,320,210
```

`video_id` là tên file không có đuôi. Có số liệu thì agent so sánh nhóm top 20% với phần còn lại;
không có thì coi mọi video là mẫu ngang nhau.

Sửa `config/products.yaml` cho sản phẩm bạn muốn bán.

## Chạy

```bash
python -m agent_thoi_trang run                    # cả 3 bước
# hoặc từng bước
python -m agent_thoi_trang analyze                # đo kỹ thuật + chép lời + Claude gắn nhãn
python -m agent_thoi_trang analyze --no-ai        # chỉ đo bằng ffmpeg, miễn phí
python -m agent_thoi_trang formula                # rút công thức kênh
python -m agent_thoi_trang scripts --max-scripts 40
```

## Kết quả (`output/`)

| File | Nội dung |
|---|---|
| `formula.md` / `formula.json` | Công thức thành công của kênh |
| `selected_scripts.md` | 10 kịch bản ≥ 90 điểm, bảng cảnh, lời thoại, chữ, điểm từng tiêu chí |
| `veo_prompts.txt` | Prompt Veo từng cảnh, dán thẳng vào Google Flow |
| `all_scripts_scored.json` | Mọi kịch bản đã chấm, kèm góp ý |

## Cách chấm điểm (thang 100)

| Tiêu chí | Điểm |
|---|---|
| Sức mạnh hook 3 giây đầu | 25 |
| Khớp công thức kênh | 20 |
| Sản phẩm rõ ràng, hấp dẫn | 15 |
| Cảm xúc / giải trí | 15 |
| CTA rõ, tự nhiên | 10 |
| Khả thi khi dựng bằng Veo | 10 |
| Tuân thủ chính sách | 5 |

Mỗi kịch bản được chấm 2 lượt độc lập rồi lấy trung bình. Bản 80-89 điểm được viết lại theo góp ý
(tối đa 2 vòng). Agent viết theo lô 10 bản cho tới khi đủ 10 bản ≥ 90 hoặc chạm `--max-scripts`.
Sửa ngưỡng trong `agent_thoi_trang/config.py`.

## Chi phí

Dùng Claude Opus 5.5. Mỗi kịch bản tốn 1 lần viết + 2 lần chấm (+ viết lại nếu cần). Hãy thử trước
với `--max-scripts 10` để xem chi phí thực tế trên tài khoản của bạn.

## Kiểm thử

```bash
pip install pytest && python -m pytest -q
```

Kiểm thử dùng LLM giả, không gọi API.
