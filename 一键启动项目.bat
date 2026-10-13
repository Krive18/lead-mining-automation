@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "START_BAT=%PROJECT_DIR%start_project.bat"

if not exist "%START_BAT%" (
    echo.
    echo [ERROR] start_project.bat was not found:
    echo %START_BAT%
    echo.
    echo Please extract the deployment ZIP first, then run this BAT from the extracted folder.
    echo.
    pause
    exit /b 1
)

call "%START_BAT%"
exit /b %ERRORLEVEL%
