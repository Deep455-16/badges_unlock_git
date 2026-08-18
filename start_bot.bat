@echo off
echo Starting Badge Bot Server...
call venv\Scripts\activate.bat
start http://127.0.0.1:5000
python app\server.py
pause
