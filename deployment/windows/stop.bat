@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "STOP_SCRIPT=%SCRIPT_DIR%stop.ps1"

if not exist "%STOP_SCRIPT%" (
    echo [ERROR] stop.ps1 was not found: %STOP_SCRIPT%
    echo Please extract the deployment ZIP first, then run this BAT from the extracted folder.
    pause
    exit /b 1
)

pushd "%SCRIPT_DIR%" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%STOP_SCRIPT%"
set "STOP_EXIT=%ERRORLEVEL%"
popd >nul

if not defined STOP_EXIT set "STOP_EXIT=1"
pause
exit /b %STOP_EXIT%
