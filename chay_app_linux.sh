#!/bin/bash
# Bấm đúp để chạy trên macOS (lần đầu: chuột phải > Open nếu máy báo chặn).
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Chưa có Python. Hãy cài Python 3.11 trở lên từ https://www.python.org/downloads/ rồi mở lại file này."
  read -r -p "Nhấn Enter để đóng..."
  exit 1
fi
if [ ! -d .venv ]; then
  echo "Lần đầu chạy: đang tạo môi trường và cài thư viện, mất vài phút..."
  python3 -m venv .venv || exit 1
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt || { echo "Cài thư viện thất bại"; read -r; exit 1; }
  .venv/bin/python -m playwright install chromium
fi
echo "Đang mở app tại http://localhost:8501 (đóng cửa sổ này để tắt app)"
.venv/bin/python -m streamlit run app/app.py --server.port 8501 --browser.gatherUsageStats false
