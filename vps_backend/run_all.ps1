# run_all.ps1 — jalankan otak FuLens (127.0.0.1:8500) + gerbang eksekutor (0.0.0.0:8000).
$root = $PSScriptRoot

function Get-Py($name) {
    $venvPy = Join-Path $root "$name\venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy } else { return "python" }
}

$brainPy = Get-Py "brain"
$execPy  = Get-Py "executor"

# Otak FuLens — internal, port 8500 (dibaca dari brain/config.py).
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root\brain'; & '$brainPy' api_server.py"
)

Start-Sleep -Seconds 4  # beri waktu otak memuat model

# Gerbang eksekutor — publik, port 8000 (dibaca dari executor/config.py ServerConfig).
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root\executor'; & '$execPy' main.py"
)

Write-Host "FuLens brain   -> http://127.0.0.1:8500  (internal)"    -ForegroundColor Green
Write-Host "Executor gate  -> http://0.0.0.0:8000    (untuk Flutter)" -ForegroundColor Green
Write-Host "Cek kesehatan  -> http://<VPS>:8000/health"               -ForegroundColor Yellow
Write-Host "Start bot dari aplikasi Flutter (atau POST /bot/start)."  -ForegroundColor Yellow
