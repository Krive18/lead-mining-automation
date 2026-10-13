@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "START_SCRIPT=%SCRIPT_DIR%start.ps1"

if not exist "%START_SCRIPT%" (
    echo [ERROR] start.ps1 was not found: %START_SCRIPT%
    echo Please extract the deployment ZIP first, then run this BAT from the extracted folder.
    pause
    exit /b 1
)

pushd "%SCRIPT_DIR%" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%"
set "START_EXIT=%ERRORLEVEL%"
popd >nul

if not defined START_EXIT set "START_EXIT=1"
pause
exit /b %START_EXIT%
