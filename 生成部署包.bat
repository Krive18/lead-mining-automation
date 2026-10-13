@echo off
setlocal
chcp 65001 >nul
title Lead Mining - Build Deploy Package
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deployment\windows\build_deploy_package.ps1"

echo.
pause
