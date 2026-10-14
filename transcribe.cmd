@echo off
if "%~1"=="" (
    echo Usage: transcribe.cmd "video URL"
    exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0transcribe-video.ps1" -Url %*
exit /b %errorlevel%
