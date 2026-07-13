# setup.ps1 — buat virtualenv & install dependency untuk brain + executor.
# Jalankan sekali di VPS: ./setup.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Setup-Service($name) {
    $dir = Join-Path $root $name
    Write-Host "`n=== [$name] menyiapkan venv ===" -ForegroundColor Cyan
    Push-Location $dir
    if (-not (Test-Path "venv")) { python -m venv venv }
    & ".\venv\Scripts\python.exe" -m pip install --upgrade pip
    & ".\venv\Scripts\python.exe" -m pip install -r requirements.txt
    Pop-Location
    Write-Host "=== [$name] selesai ===" -ForegroundColor Green
}

Setup-Service "brain"
Setup-Service "executor"

Write-Host "`nSemua dependency terpasang. Jalankan: ./run_all.ps1" -ForegroundColor Yellow
Write-Host "Ingat: terminal MT5 harus sudah login sebelum start bot." -ForegroundColor Yellow
