param([string]$Pi = 'mark@192.168.10.52')

# Opens an SSH tunnel to the agent on the Raspberry Pi and starts LangSmith Studio.
# Studio always connects to http://127.0.0.1:2024 on this PC; the tunnel forwards
# that port to the Pi, so the agent API never has to be public.
$ErrorActionPreference = 'Stop'
$studio = 'https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024'

if (Get-NetTCPConnection -LocalPort 2024 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 2024 ist belegt (laeuft der lokale Agent noch?). Bitte zuerst beenden.'
}

Write-Host "Verbinde mit $Pi ..."
$tunnel = Start-Process -FilePath ssh -PassThru -WindowStyle Hidden `
    -ArgumentList '-N', '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=30', '-L', '2024:127.0.0.1:2024', $Pi

for ($i = 0; $i -lt 30; $i++) {
    try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:2024/ok' -TimeoutSec 2; break } catch {}
    if ($tunnel.HasExited) { throw 'SSH-Tunnel fehlgeschlagen. Ist der Pi erreichbar und der SSH-Schluessel eingerichtet?' }
    Start-Sleep -Milliseconds 500
}

Write-Host 'Tunnel steht. Studio wird geoeffnet.'
Start-Process $studio
Write-Host 'Dieses Fenster offen lassen. Enter druecken, um den Tunnel zu schliessen.'
$null = Read-Host
Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
