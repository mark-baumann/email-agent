param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskLanggraph = Join-Path $PSScriptRoot '.venv\Scripts\langgraph.exe'
$taskLogs = Join-Path $PSScriptRoot '.inbox-logs'

if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Python-Umgebung fehlt. Bitte zuerst uv sync --extra dev ausfuehren.'
}
New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null

function Test-Endpoint([string]$Address) {
    try {
        $null = Invoke-RestMethod -Uri $Address -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

function Wait-Endpoint([string]$Address, $TaskProcess) {
    for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
        if (Test-Endpoint $Address) { return }
        if ($TaskProcess.HasExited) { throw "Start fehlgeschlagen. Details in $taskLogs" }
        Start-Sleep -Milliseconds 500
    }
    throw "Server noch nicht erreichbar. Details in $taskLogs"
}

if (-not (Test-Endpoint 'http://127.0.0.1:2024/ok')) {
    Write-Host 'Starte E-Mail-Agent ...'
    $taskConfig = Join-Path $PSScriptRoot 'langgraph.imap.json'
    $taskAgent = Start-Process -FilePath $taskLanggraph -WindowStyle Hidden -PassThru `
        -ArgumentList ('dev --config "{0}" --no-browser' -f $taskConfig) `
        -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput (Join-Path $taskLogs 'agent.log') `
        -RedirectStandardError (Join-Path $taskLogs 'agent-error.log')
    Wait-Endpoint 'http://127.0.0.1:2024/ok' $taskAgent
    Write-Host "Agent-Prozess: $($taskAgent.Id)"
}

if (-not (Test-Endpoint 'http://127.0.0.1:8080/api/status')) {
    Write-Host 'Starte Postfach-Oberflaeche ...'
    $taskUI = Start-Process -FilePath $taskPython -WindowStyle Hidden -PassThru `
        -ArgumentList '-m email_assistant.inbox' -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput (Join-Path $taskLogs 'inbox.log') `
        -RedirectStandardError (Join-Path $taskLogs 'inbox-error.log')
    Wait-Endpoint 'http://127.0.0.1:8080/api/status' $taskUI
    Write-Host "Postfach-Prozess: $($taskUI.Id)"
}

Write-Host 'Postfach bereit: http://127.0.0.1:8080'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8080' }
