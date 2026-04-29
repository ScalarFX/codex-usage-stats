# Builds a standalone Windows executable using PyInstaller.
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "Installing pyinstaller..."
    python -m pip install --user pyinstaller
}

if (Test-Path build)  { Remove-Item -Recurse -Force build }
if (Test-Path dist)   { Remove-Item -Recurse -Force dist }
Get-ChildItem -Filter "*.spec" | Remove-Item -Force -ErrorAction SilentlyContinue

pyinstaller `
    --onefile `
    --name codex-stats `
    --add-data "web;web" `
    --noconfirm `
    --clean `
    -p . `
    codex_stats/__main__.py

Write-Host ""
Write-Host "Built: dist\codex-stats.exe"
