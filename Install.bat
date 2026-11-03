@echo off
setlocal
title Sage Study installer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
set RESULT=%errorlevel%
if not "%SAGE_INSTALL_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
