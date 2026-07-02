Set-Location $PSScriptRoot
Write-Host "Starting FMS backend on http://localhost:8002 ..." -ForegroundColor Cyan
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
