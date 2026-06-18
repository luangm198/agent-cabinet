@echo off
chcp 65001 >nul
title AI Team Meeting - running
cd /d "%~dp0"
echo.
echo  Starting the AI meeting room... your browser will open automatically.
echo  KEEP THIS WINDOW OPEN while you use the app.
echo  To stop the app: close this window.
echo.
start "" http://localhost:8000
set "PYEXE=C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PYEXE%" set "PYEXE=python"
"%PYEXE%" -m uvicorn server:app --port 8000
pause
