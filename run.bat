@echo off
setlocal EnableDelayedExpansion
title VideoAudioTool Web Server
cd /d "%~dp0"

echo ========================================================
echo        VideoAudioTool Web Server
echo ========================================================
echo.

if not exist "%~dp0app.py" goto BAD_PATH
where python.exe >nul 2>nul
if errorlevel 1 goto NO_PYTHON
python -c "import flask" >nul 2>nul
if errorlevel 1 goto NO_FLASK
where ffmpeg.exe >nul 2>nul
if errorlevel 1 goto NO_FFMPEG
where ffprobe.exe >nul 2>nul
if errorlevel 1 goto NO_FFPROBE

echo [Local] http://127.0.0.1:5000
echo [LAN / Mobile]
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /i "IPv4"') do (
    set "VIDEO_TOOL_IP=%%i"
    set "VIDEO_TOOL_IP=!VIDEO_TOOL_IP: =!"
    echo   http://!VIDEO_TOOL_IP!:5000
)
echo.
echo Starting server and checking http://127.0.0.1:5000 ...

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $proc=Start-Process -FilePath 'python.exe' -ArgumentList '-m','flask','--app','app.py','run','--host=0.0.0.0','--port=5000' -WorkingDirectory '%CD%' -NoNewWindow -PassThru; $ready=$false; for($i=0; $i -lt 20; $i++){ if($proc.HasExited){ break }; try { $response=Invoke-WebRequest -Uri 'http://127.0.0.1:5000/' -UseBasicParsing -TimeoutSec 2; if($response.StatusCode -eq 200){ $ready=$true; break } } catch {}; Start-Sleep -Seconds 1 }; if(-not $ready){ if(-not $proc.HasExited){ Stop-Process -Id $proc.Id -Force }; exit 1 }; Write-Host ''; Write-Host '[OK] Server is running. Keep this window open.'; Write-Host 'Press Ctrl+C to stop the server.'; Start-Process 'http://127.0.0.1:5000'; Wait-Process -Id $proc.Id"
if errorlevel 1 goto START_ERROR
exit /b 0

:BAD_PATH
echo [ERROR] app.py was not found next to run.bat.
goto FAILED

:NO_PYTHON
echo [ERROR] Python was not found in PATH.
goto FAILED

:NO_FLASK
echo [ERROR] Flask is not installed. Run: python -m pip install -r requirements.txt
goto FAILED

:NO_FFMPEG
echo [ERROR] ffmpeg.exe was not found in PATH.
goto FAILED

:NO_FFPROBE
echo [ERROR] ffprobe.exe was not found in PATH.
goto FAILED

:START_ERROR
echo [ERROR] The server did not start or the health check failed.

:FAILED
echo.
pause
exit /b 1
