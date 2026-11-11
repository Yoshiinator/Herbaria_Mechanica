$ErrorActionPreference = "SilentlyContinue"
$proc = Start-Process python -ArgumentList "C:\SharedFiles\pump_api_update.py" -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 3
if ($proc -and !$proc.HasExited) {
    Write-Host "Started PID:" $proc.Id
} else {
    Write-Host "Failed to start"
}