$action = New-ScheduledTaskAction -Execute "python" -Argument "C:\SharedFiles\arduino_api.py" -WorkingDirectory "C:\SharedFiles"
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Unregister-ScheduledTask -TaskName "ArduinoAPI" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "ArduinoAPI" -Action $action -Trigger $trigger -Settings $settings -Force

Start-ScheduledTask -TaskName "ArduinoAPI"
Start-Sleep -Seconds 3
$st = Get-ScheduledTask -TaskName "ArduinoAPI"
Write-Host "State:" $st.State
Write-Host "LastRunTime:" $st.LastRunTime
Write-Host "LastResult:" $st.LastTaskResult