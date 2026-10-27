# Starts one service of the email agent in the foreground and writes its output
# to .inbox-logs. The scheduled tasks from Install-EmailAgent.ps1 call this
# script, so a crashed service keeps its exit code and Windows can restart it.
param(
    [Parameter(Mandatory = $true)][ValidateSet('agent', 'inbox', 'caddy')][string]$Service,
    [string]$RepoPath,
    [string]$CaddyExe = 'caddy.exe'
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

if (-not $RepoPath) { $RepoPath = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path
Set-Location -LiteralPath $RepoPath

switch ($Service) {
    'agent' {
        $executable = Join-Path $RepoPath '.venv\Scripts\langgraph.exe'
        $arguments = @('dev', '--config', 'langgraph.imap.json', '--no-browser',
                       '--no-reload', '--host', '127.0.0.1', '--port', '2024')
    }
    'inbox' {
        $executable = Join-Path $RepoPath '.venv\Scripts\python.exe'
        $arguments = @('-m', 'email_assistant.inbox')
    }
    'caddy' {
        $executable = $CaddyExe
        $arguments = @('run', '--config', (Join-Path $PSScriptRoot 'Caddyfile'), '--adapter', 'caddyfile')
    }
}

if ($Service -ne 'caddy' -and -not (Test-Path -LiteralPath $executable)) {
    throw "Python-Umgebung fehlt: $executable. Bitte zuerst uv sync --frozen ausfuehren."
}

$logDirectory = Join-Path $RepoPath '.inbox-logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$log = Join-Path $logDirectory "$Service.log"
if ((Test-Path -LiteralPath $log) -and ((Get-Item -LiteralPath $log).Length -gt 5MB)) {
    Move-Item -LiteralPath $log -Destination "$log.1" -Force
}

"$(Get-Date -Format 's') --- Start $Service ---" | Add-Content -LiteralPath $log
& $executable @arguments 2>&1 |
    ForEach-Object { '{0} {1}' -f (Get-Date -Format 's'), $_ } |
    Add-Content -LiteralPath $log
$code = $LASTEXITCODE
"$(Get-Date -Format 's') --- Ende $Service (Exitcode $code) ---" | Add-Content -LiteralPath $log
exit $code
