# Stops the email agent on Windows and removes its scheduled tasks.
# Zugangsdaten (.env), Datenbank und Logs bleiben erhalten.
param([switch]$KeepFirewallRule)

$ErrorActionPreference = 'Stop'
$taskFolder = '\EmailAgent\'

$tasks = Get-ScheduledTask -TaskPath $taskFolder -ErrorAction SilentlyContinue
if (-not $tasks) {
    Write-Host 'Keine Aufgaben unter \EmailAgent\ gefunden.'
} else {
    $tasks | Stop-ScheduledTask -ErrorAction SilentlyContinue
    foreach ($task in $tasks) {
        Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath $taskFolder -Confirm:$false
        Write-Host "Aufgabe entfernt: $taskFolder$($task.TaskName)"
    }
}

if (-not $KeepFirewallRule) {
    if (Get-NetFirewallRule -DisplayName 'Email-Agent HTTP/HTTPS' -ErrorAction SilentlyContinue) {
        Remove-NetFirewallRule -DisplayName 'Email-Agent HTTP/HTTPS'
        Write-Host 'Firewall-Regel entfernt.'
    }
}
