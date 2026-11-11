# Run SAM3 FastAPI container (Windows PowerShell)
# Run from the folder containing docker-compose.yml

Set-Location $PSScriptRoot

Write-Host "Building and starting SAM3 container..." -ForegroundColor Cyan
docker compose up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed." -ForegroundColor Red
    exit 1
}

Write-Host "Container is running. API: http://localhost:8222" -ForegroundColor Green
Write-Host "  Health: http://localhost:8222/health" -ForegroundColor Gray
Write-Host "  GUI:    http://localhost:8222/gui" -ForegroundColor Gray
