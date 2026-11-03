@echo off
setlocal
title Sage Study uninstaller
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\uninstall.ps1" %*
set RESULT=%errorlevel%
if not "%SAGE_INSTALL_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
