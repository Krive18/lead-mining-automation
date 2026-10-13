@echo off
setlocal
title Lead Mining - Start Project

set "PROJECT_DIR=%~dp0"
set "START_SCRIPT=%PROJECT_DIR%deployment\windows\start.ps1"

if not exist "%START_SCRIPT%" (
    echo.
    echo [ERROR] start.ps1 was not found:
    echo %START_SCRIPT%
    echo.
    echo Do NOT run this file directly inside the ZIP preview window.
    echo Please right-click the deployment ZIP, choose "Extract All",
    echo open the extracted project folder, then run this BAT again.
    echo.
    echo Current directory: %PROJECT_DIR%
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Lead Mining Local Console
echo ========================================
echo.
echo Starting backend and frontend...
echo.

pushd "%PROJECT_DIR%" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%"
set "START_EXIT=%ERRORLEVEL%"
popd >nul

if not defined START_EXIT set "START_EXIT=1"

echo.
if not "%START_EXIT%"=="0" (
    echo ========================================
    echo Project failed to start. Please send the red error text to the developer.
    echo ========================================
    echo.
    pause
    exit /b %START_EXIT%
)

echo ========================================
echo Project started.
echo Frontend: http://127.0.0.1:5173/
echo Backend : http://127.0.0.1:8000/api/health
echo Logs    : %PROJECT_DIR%runtime_logs
echo ========================================
echo.
pause
exit /b 0
