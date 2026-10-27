# Registers the email agent as scheduled tasks on Windows so that it runs
# continuously and comes back after a restart. See deploy/windows/README.md.
#
#   Dauerbetrieb (empfohlen, PowerShell als Administrator):
#     .\deploy\windows\Install-EmailAgent.ps1
#   Ohne Administratorrechte (startet erst nach der Anmeldung):
#     .\deploy\windows\Install-EmailAgent.ps1 -AtLogon
param(
    [string]$RepoPath,
    [string]$Domain = 'email-agent.markb.de',
    [switch]$AtLogon,
    [switch]$SkipCaddy,
    [string]$CaddyExe,
    [switch]$SkipFirewall
)

$ErrorActionPreference = 'Stop'
$taskFolder = '\EmailAgent\'
$scriptPath = Join-Path $PSScriptRoot 'Run-Service.ps1'

if (-not $RepoPath) { $RepoPath = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$elevated = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$userId = $identity.Name

if (-not $AtLogon -and -not $elevated) {
    throw 'Fuer den Dauerbetrieb PowerShell als Administrator starten, oder -AtLogon verwenden (startet erst nach der Anmeldung).'
}

# 1. Voraussetzungen im Projektordner
foreach ($required in @('.venv\Scripts\python.exe', '.venv\Scripts\langgraph.exe', 'langgraph.imap.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath $required))) {
        throw "$required fehlt in $RepoPath. Bitte zuerst uv sync --frozen ausfuehren."
    }
}
$envFile = Join-Path $RepoPath '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env fehlt in $RepoPath. Bitte .env.example kopieren und Zugangsdaten eintragen."
}
$envText = Get-Content -LiteralPath $envFile -Raw
if ($envText -match 'EMAIL_PASSWORD=\s*(your_mailbox_password)?\s*(\r?\n|$)') {
    throw 'In .env fehlt noch das echte EMAIL_PASSWORD.'
}
if (-not $SkipCaddy -and $envText -notmatch [regex]::Escape($Domain)) {
    Write-Warning "In .env fehlt die Domain. Bitte ergaenzen: INBOX_ALLOWED_HOSTS=127.0.0.1,localhost,$Domain"
}

# 2. Dienste als geplante Aufgaben registrieren
function Test-Endpoint([string]$Address) {
    try {
        $null = Invoke-RestMethod -Uri $Address -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

Get-ScheduledTask -TaskPath $taskFolder -ErrorAction SilentlyContinue |
    Stop-ScheduledTask -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
foreach ($running in @('http://127.0.0.1:2024/ok', 'http://127.0.0.1:8080/api/status')) {
    if (Test-Endpoint $running) {
        throw "Auf diesem Rechner laeuft bereits eine Instanz ($running). Bitte zuerst beenden, z. B. die per Start-Inbox.cmd gestarteten Prozesse."
    }
}

function Register-AgentTask {
    param([string]$Name, [string]$Service, [string]$Description, [string[]]$Extra = @())

    $argumentList = @('-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                      '-ExecutionPolicy', 'Bypass', '-File', "`"$scriptPath`"",
                      '-Service', $Service, '-RepoPath', "`"$RepoPath`"") + $Extra
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument ($argumentList -join ' ') -WorkingDirectory $RepoPath
    if ($AtLogon) {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    } else {
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType S4U -RunLevel Limited
    }
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew `
        -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    Register-ScheduledTask -TaskName $Name -TaskPath $taskFolder -Description $Description `
        -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "Aufgabe eingerichtet: $taskFolder$Name"
}

Register-AgentTask -Name 'Agent' -Service 'agent' -Description 'LangGraph-Server des E-Mail-Agenten (127.0.0.1:2024)'
Register-AgentTask -Name 'Inbox' -Service 'inbox' -Description 'Postfach-Oberflaeche und IMAP-Abruf (127.0.0.1:8080)'

# 3. Caddy fuer HTTPS und Anmeldung unter der Domain
$caddyPath = $null
if (-not $SkipCaddy) {
    if ($CaddyExe) {
        $caddyPath = (Resolve-Path -LiteralPath $CaddyExe).Path
    } else {
        $found = Get-Command 'caddy.exe' -ErrorAction SilentlyContinue
        if (-not $found) {
            throw 'caddy.exe nicht gefunden. Installieren mit: winget install CaddyServer.Caddy (danach PowerShell neu starten) oder -SkipCaddy verwenden.'
        }
        $caddyPath = $found.Source
    }
    $caddyfile = Join-Path $PSScriptRoot 'Caddyfile'
    if ((Get-Content -LiteralPath $caddyfile -Raw) -match 'REPLACE_WITH_BCRYPT_HASH') {
        throw "In $caddyfile fehlt das Anmeldepasswort. Hash mit 'caddy hash-password' erzeugen und eintragen."
    }
    Register-AgentTask -Name 'Caddy' -Service 'caddy' -Description "HTTPS-Proxy fuer $Domain" -Extra @('-CaddyExe', "`"$caddyPath`"")

    if (-not $SkipFirewall) {
        if ($elevated) {
            Remove-NetFirewallRule -DisplayName 'Email-Agent HTTP/HTTPS' -ErrorAction SilentlyContinue
            New-NetFirewallRule -DisplayName 'Email-Agent HTTP/HTTPS' -Direction Inbound -Action Allow `
                -Protocol TCP -LocalPort 80, 443 -Program $caddyPath | Out-Null
            Write-Host 'Firewall-Regel fuer Port 80 und 443 gesetzt.'
        } else {
            Write-Warning 'Ohne Administratorrechte keine Firewall-Regel. Port 80 und 443 fuer caddy.exe spaeter freigeben.'
        }
    }
}

# 4. Starten und pruefen
foreach ($name in @('Agent', 'Inbox') + $(if ($caddyPath) { 'Caddy' } else { @() })) {
    Start-ScheduledTask -TaskName $name -TaskPath $taskFolder
}

function Wait-Endpoint([string]$Address) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if (Test-Endpoint $Address) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$logs = Join-Path $RepoPath '.inbox-logs'
if (-not (Wait-Endpoint 'http://127.0.0.1:2024/ok')) { throw "Agent nicht erreichbar. Details in $logs\agent.log" }
if (-not (Wait-Endpoint 'http://127.0.0.1:8080/api/status')) { throw "Postfach nicht erreichbar. Details in $logs\inbox.log" }

Write-Host ''
Write-Host 'Dienste laufen: http://127.0.0.1:8080'
if ($caddyPath) { Write-Host "Nach DNS- und Router-Einrichtung: https://$Domain" }
if ($AtLogon) {
    Write-Host 'Start erfolgt bei der naechsten Anmeldung.'
} else {
    Write-Host 'Start erfolgt beim naechsten Hochfahren, auch ohne Anmeldung.'
}
Write-Host "Logs: $logs"
