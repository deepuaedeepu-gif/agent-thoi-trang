# Agent video thời trang

## App điều khiển

```bash
pip install -r requirements.txt
python -m playwright install chromium     # cho chức năng quét Facebook
streamlit run app/app.py                  # mở http://localhost:8501
```

| Tab | Đã có | Bước sau |
|---|---|---|
| Công thức thành công | Đăng nhập Facebook trong cửa sổ riêng, quét link trang/reel, chọn 5-20 reel nhiều view nhất, tải về, phân tích, lưu công thức có tên. Hoặc tải video lên trực tiếp. | |
| Kho Người mẫu | Nhân vật AI mặc định, tạo nhân vật AI mới kèm ảnh | Người dẫn là người thật, có bước xác minh bằng video đồng ý |
| Kho voice | 10 giọng tiếng Việt Google Cloud TTS | FPT.AI, ElevenLabs, nghe thử, tạo giọng từ mp3 (có bản ghi đồng ý) |
| Dựng video | Chọn công thức, người dẫn, voice, ảnh sản phẩm, số kịch bản, ngưỡng điểm, tạo kịch bản; tải gói prompt + ảnh cho Google Flow | Tự tạo video qua Veo (Gemini API) và Grok Imagine (xAI API) |

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
