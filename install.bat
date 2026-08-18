@echo off
echo Installing dependencies for Badge Bot...
python -m venv venv
call venv\Scripts\activate.bat
pip install -r app\requirements.txt
echo Installation complete! You can now run start_bot.bat.
pause
