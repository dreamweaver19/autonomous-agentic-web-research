@echo off
echo Starting Autonomous Research Agent Backend...
cd /d "%~dp0backend"
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
