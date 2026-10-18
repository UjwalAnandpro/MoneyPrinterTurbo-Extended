@echo off
cd /d "C:\Users\ujwal\.gemini\antigravity-ide\scratch\MoneyPrinterTurbo-Extended"

set PYTHONPATH=C:\Users\ujwal\.gemini\antigravity-ide\scratch\MoneyPrinterTurbo-Extended
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:32
set CUDNN_LOGINFO_DBG=0
set PYTHONWARNINGS=ignore::UserWarning

if not defined CHATTERBOX_CFG_WEIGHT set CHATTERBOX_CFG_WEIGHT=0.2
if not defined CHATTERBOX_CHUNK_THRESHOLD set CHATTERBOX_CHUNK_THRESHOLD=800

start /b "" ".\.venv\Scripts\python.exe" status_monitor.py

:RETRY_LOOP
".\.venv\Scripts\python.exe" daily_tech_video.py >> storage\daily_runner.log 2>&1

:: Verify if completed in daily_state.json, retry if not
".\.venv\Scripts\python.exe" -c "import json, os, sys; p='storage/daily_state.json'; d=json.load(open(p, 'r', encoding='utf-8')) if os.path.exists(p) else {}; sys.exit(0 if d.get('completed') else 1)"
if errorlevel 1 (
    echo Pipeline not completed yet. Retrying in 15 seconds... >> storage\daily_runner.log
    timeout /t 15 /nobreak >nul
    goto RETRY_LOOP
)

echo Daily automation successfully completed! >> storage\daily_runner.log

