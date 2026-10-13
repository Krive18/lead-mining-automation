@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "LAUNCHER=%~dp0setup_environment.bat"
if exist "%LAUNCHER%" goto :run_launcher
echo.
echo [ERROR] The complete deployment folder was not found.
echo Please extract Automation-AI.zip first, then run this BAT again.
echo.
pause
exit /b 1

:run_launcher
call "%LAUNCHER%" %*
exit /b %ERRORLEVEL%
