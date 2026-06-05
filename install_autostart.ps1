# Register vrfu-ai web UI to start at Windows logon.
# Run from an elevated OR normal PowerShell — this uses Task Scheduler scoped to the current user.
#
# To remove: .\uninstall_autostart.ps1
# To inspect: open Task Scheduler -> Task Scheduler Library -> "vrfu-ai web UI"

$ErrorActionPreference = "Stop"

$TaskName = "vrfu-ai web UI"
$ScriptPath = Join-Path $PSScriptRoot "launch_website_autostart.bat"

if (-not (Test-Path $ScriptPath)) {
    throw "Cannot find $ScriptPath"
}

# Remove any prior registration so this is idempotent.
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task '$TaskName'."
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$ScriptPath`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Run minimized, only when logged in interactively, no battery restrictions.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Starts the local vrfu-ai web server (http://localhost:8765) at user logon." | Out-Null

Write-Host "Registered scheduled task '$TaskName'."
Write-Host "It will run '$ScriptPath' at logon as $env:USERNAME."
Write-Host ""
Write-Host "Test now without rebooting:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Stop running task:           Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Host "Remove autostart:            .\uninstall_autostart.ps1"
