# Remove the vrfu-ai web UI autostart task. Does not stop a currently-running server.

$TaskName = "vrfu-ai web UI"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Task '$TaskName' is not registered. Nothing to do."
    return
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Unregistered scheduled task '$TaskName'."
Write-Host "The web server (if running) was NOT stopped. To stop it now:"
Write-Host "  powershell -c `"Get-NetTCPConnection -LocalPort 8765 -LocalAddress 127.0.0.1 -State Listen | %% { Stop-Process -Id `$_.OwningProcess -Force }`""
