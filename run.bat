@echo off
REM Start Video Audio Editor Web UI Server with Hot-Reload enabled
cd /d %~dp0
echo Starting Video Audio Editor Web UI Server in Debug/Hot-Reload Mode...
start http://127.0.0.1:5000

set FLASK_APP=app.py
set FLASK_DEBUG=1
python -m flask run --host=127.0.0.1 --port=5000

if errorlevel 1 goto ERROR
goto END

:ERROR
echo An error occurred while launching the server.
pause
exit /b 1

:END
