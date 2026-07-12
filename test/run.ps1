# Launch FMS in the DEMO / TEST environment (pre-seeded SQLite, API-push mode).
# Usage:  .\test\run.ps1
$env:FMS_ENV_FILE = Join-Path $PSScriptRoot "demo.env"
Set-Location (Split-Path $PSScriptRoot -Parent)
Write-Host "FMS demo environment — http://localhost:8002" -ForegroundColor Cyan
Write-Host "Sign in: admin@fms.demo / DemoAdmin!2026" -ForegroundColor Cyan
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
