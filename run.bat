@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [codex-stats] Python 3.11+ not found on PATH.
    echo Install from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)

python -m codex_stats %*
