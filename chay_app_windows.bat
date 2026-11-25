@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Agent video thoi trang

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (
  where python >nul 2>nul
  if %errorlevel%==0 (set PY=python) else (
    echo Chua co Python. Hay cai Python 3.11 tro len tu https://www.python.org/downloads/
    echo Khi cai, nho tick "Add python.exe to PATH". Sau do mo lai file nay.
    pause
    exit /b 1
  )
)

if not exist .venv (
  echo Lan dau chay: dang tao moi truong va cai thu vien, mat vai phut...
  %PY% -m venv .venv || (echo Khong tao duoc moi truong Python & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || (echo Cai thu vien that bai & pause & exit /b 1)
  .venv\Scripts\python -m playwright install chromium
)

echo Dang mo app tai http://localhost:8501 ... (dong cua so nay de tat app)
.venv\Scripts\python -m streamlit run app\app.py --server.port 8501 --browser.gatherUsageStats false
pause
