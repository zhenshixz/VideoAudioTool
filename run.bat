@echo off
setlocal EnableDelayedExpansion
title VideoAudioTool Web Server
cd /d "%~dp0"

echo ========================================================
echo        Starting VideoAudioTool Web Server (Debug)
echo ========================================================
echo.
echo [Local Access]: http://127.0.0.1:5000
echo.
echo [LAN / Mobile Access Options]:
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP_ADDR=%%i
    set IP_ADDR=!IP_ADDR: =!
    echo   - http://!IP_ADDR!:5000
)
echo.
echo (Tip: On home WiFi, usually pick the one starting with 192.168)
echo.

start http://127.0.0.1:5000

set FLASK_APP=app.py
set FLASK_DEBUG=1
python -m flask run --host=0.0.0.0 --port=5000

if errorlevel 1 goto ERROR
goto END

:ERROR
echo.
echo [ERROR] Failed to start server.
pause
exit /b 1

:END
pause
