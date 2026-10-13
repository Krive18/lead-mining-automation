@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Automation-AI - Setup Environment

set "PROJECT_DIR=%~dp0"
set "SETUP_SCRIPT=%PROJECT_DIR%deployment\windows\setup_env.ps1"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%SETUP_SCRIPT%" goto :missing_setup
if not exist "%POWERSHELL_EXE%" goto :missing_powershell
goto :run_setup

:missing_setup
echo.
echo [ERROR] The complete deployment folder was not found.
echo This usually happens when this BAT is opened inside the ZIP preview window.
echo Right-click Automation-AI.zip, choose "Extract All", then run this BAT
echo from the extracted Automation-AI folder.
echo.
pause
exit /b 1

:missing_powershell
echo.
echo [ERROR] Windows PowerShell was not found.
echo.
pause
exit /b 1

:run_setup

pushd "%PROJECT_DIR%" >nul
"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_SCRIPT%" %*
set "SETUP_EXIT=%ERRORLEVEL%"
popd >nul

if not defined SETUP_EXIT set "SETUP_EXIT=1"

echo.
if "%SETUP_EXIT%"=="0" goto :setup_success
echo Setup failed. See runtime_logs\setup_environment.log for details.
echo.
pause
exit /b %SETUP_EXIT%

:setup_success
echo Setup finished. You can run start_project.bat now.
echo.
pause
exit /b 0
