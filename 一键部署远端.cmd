@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy_remote.ps1" %*
if %ERRORLEVEL% NEQ 0 pause
