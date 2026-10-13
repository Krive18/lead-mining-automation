@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "INSTALL_SCRIPT=%SCRIPT_DIR%install.ps1"

if not exist "%INSTALL_SCRIPT%" (
    echo.
    echo [ERROR] install.ps1 was not found:
    echo %INSTALL_SCRIPT%
    echo.
    echo Please extract the deployment ZIP first, then run this BAT from the extracted folder.
    echo.
    pause
    exit /b 1
)

pushd "%SCRIPT_DIR%" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_SCRIPT%"
set "INSTALL_EXIT=%ERRORLEVEL%"
popd >nul

if not defined INSTALL_EXIT set "INSTALL_EXIT=1"

if "%INSTALL_EXIT%"=="0" (
    echo Install finished.
) else (
    echo Install failed. Please check the red error text above.
)
pause
exit /b %INSTALL_EXIT%
