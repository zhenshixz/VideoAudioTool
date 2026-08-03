@echo off
setlocal
title VideoAudioTool Phone Tools Installer
cd /d "%~dp0"

set "TOOLS_ROOT=%~dp0tools"
set "ADB_EXE=%TOOLS_ROOT%\platform-tools\adb.exe"
set "ZIP_PATH=%TEMP%\VideoAudioTool-platform-tools.zip"
set "DOWNLOAD_URL=https://dl.google.com/android/repository/platform-tools-latest-windows.zip"

echo ========================================================
echo   VideoAudioTool Android Phone Tools Installer
echo ========================================================
echo.

if exist "%ADB_EXE%" goto VERIFY

where powershell.exe >nul 2>nul
if errorlevel 1 goto NO_POWERSHELL

echo [1/3] Checking project path...
if not exist "%~dp0app.py" goto BAD_PATH
if not exist "%TOOLS_ROOT%" mkdir "%TOOLS_ROOT%"

echo [2/3] Downloading official Android SDK Platform-Tools...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri '%DOWNLOAD_URL%' -OutFile '%ZIP_PATH%'"
if errorlevel 1 goto DOWNLOAD_ERROR

echo [3/3] Extracting phone tools...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%TOOLS_ROOT%' -Force"
if errorlevel 1 goto EXTRACT_ERROR

:VERIFY
if not exist "%ADB_EXE%" goto VERIFY_ERROR
echo.
echo Phone tools installed successfully:
"%ADB_EXE%" version
if errorlevel 1 goto VERIFY_ERROR
echo.
echo Return to VideoAudioTool and click Check Phone Connection.
echo Keep this window open if you need to read an error message.
pause
exit /b 0

:BAD_PATH
echo [ERROR] app.py was not found next to this installer.
goto FAILED

:NO_POWERSHELL
echo [ERROR] powershell.exe is required but was not found.
goto FAILED

:DOWNLOAD_ERROR
echo [ERROR] The official Android tools download failed.
goto FAILED

:EXTRACT_ERROR
echo [ERROR] The Android tools archive could not be extracted.
goto FAILED

:VERIFY_ERROR
echo [ERROR] adb.exe is missing or cannot run.
goto FAILED

:FAILED
echo.
echo Installation failed. Review the message above and try again.
pause
exit /b 1
