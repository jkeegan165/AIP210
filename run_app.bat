@echo off

REM Launch a minimized instance of this script and exit current window
if "%1"=="min" goto start

start "" /min cmd /c "%~f0" min
exit

:start
echo Starting AIP-210 Exam Trainer...

REM Install dependencies silently
pip install -r requirements.txt >nul 2>&1

REM Start Flask app
start "" /min cmd /c python app.py

REM Wait for server to spin up
timeout /t 2 >nul

REM Open browser
start http://127.0.0.1:5000