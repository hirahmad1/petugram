@echo off
cd /d "%~dp0"
py -3.14 -m pip install -r requirements.txt -q
py -3.14 -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload
pause
