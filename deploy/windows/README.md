# Windows: Dauerbetrieb unter email-agent.markb.de

Der Agent läuft dauerhaft auf dem Windows-PC: zwei geplante Aufgaben starten
LangGraph-Server und Postfach-Oberfläche beim Hochfahren neu, Caddy stellt die
Oberfläche unter `https://email-agent.markb.de` mit Passwortschutz bereit.
Vorbereitet für Windows 10/11 und PowerShell 5.1. Noch nicht auf dem echten
Rechner und nicht auf der Domain getestet — die Schritte unten sind der
Erstdurchlauf.

Der Agent liest Mails und schreibt Entwürfe, **versendet aber nichts ohne
Freigabe** in der Oberfläche.

## 1. Voraussetzungen

* [Git](https://git-scm.com/download/win) und
  [uv](https://docs.astral.sh/uv/getting-started/installation/)
* Der PC muss durchlaufen, sonst holt der Agent keine Mails ab:

  ```powershell
  powercfg /change standby-timeout-ac 0
  powercfg /change hibernate-timeout-ac 0
  ```

  Der Bildschirm darf ausgehen; der Rechner darf nicht schlafen.

## 2. Repository und Zugangsdaten

```powershell
cd $HOME
git clone --branch claude/windows-deploy https://github.com/mark-baumann/email-agent.git
cd email-agent
uv sync --frozen
Copy-Item .env.example .env
notepad .env
```

Falls bereits geklont: `git fetch origin` und
`git switch claude/windows-deploy`, danach `git pull --ff-only`. Sobald dieser
Branch gemerged ist, genügt `claude/imap-one-com-email-gk8i3s`.

In `.env` die echten Werte setzen:

* `EMAIL_ADDRESS` und `EMAIL_PASSWORD` — das Postfach (one.com-Voreinstellungen
  für IMAP/SMTP sind bereits eingetragen)
* `MODEL_PROVIDER=openai` mit `OPENAI_API_KEY` **oder**
  `MODEL_PROVIDER=ollama_cloud` mit `OLLAMA_API_KEY`
* `LANGSMITH_TRACING=false`, solange kein gültiger LangSmith-Key eingetragen
  ist — sonst scheitert jeder Trace-Upload mit `403`
* Domainzugriff freischalten:

  ```dotenv
  INBOX_ALLOWED_HOSTS=127.0.0.1,localhost,email-agent.markb.de
  ```

`.env` enthält Passwörter: nicht ins Git aufnehmen (steht bereits in
`.gitignore`) und nicht in Tickets oder Chats kopieren.

## 3. Anmeldung für die Oberfläche festlegen

Caddy installieren und das Passwort als Hash hinterlegen:

```powershell
winget install CaddyServer.Caddy
```

PowerShell danach neu öffnen, damit `caddy.exe` im Pfad liegt.

```powershell
caddy hash-password
```

Das ausgegebene `$2a$...` in `deploy\windows\Caddyfile` anstelle von
`REPLACE_WITH_BCRYPT_HASH` eintragen. Benutzername ist `mark`; Domain im selben
File anpassen, falls eine andere verwendet wird.

## 4. Dienste einrichten

PowerShell **als Administrator** im Projektordner:

```powershell
.\deploy\windows\Install-EmailAgent.ps1
```

Das richtet unter `\EmailAgent\` drei geplante Aufgaben ein (`Agent`, `Inbox`,
`Caddy`), setzt eine Firewall-Regel für Port 80 und 443, startet alles und
wartet, bis beide Dienste antworten. Die Aufgaben starten beim Hochfahren —
auch ohne Anmeldung — und werden nach einem Absturz neu gestartet.

Ohne Administratorrechte:

```powershell
.\deploy\windows\Install-EmailAgent.ps1 -AtLogon
```

Dann startet der Agent erst nach der Windows-Anmeldung, und die Firewall-Regel
muss einmal von Hand bestätigt werden.

Weitere Schalter: `-SkipCaddy` (nur lokal unter `http://127.0.0.1:8080`),
`-Domain andere.domain.de`, `-CaddyExe C:\Pfad\caddy.exe`, `-SkipFirewall`.

Läuft bereits eine Instanz über `Start-Inbox.cmd`, bricht das Skript ab. Diese
Prozesse vorher beenden; es darf immer nur **eine** Instanz Mails bearbeiten.

## 5. Domain und Router

* **DNS:** A-Record für `email-agent.markb.de` auf die öffentliche IP des
  Anschlusses. Nur passende A/AAAA-Einträge setzen; ein falscher
  IPv6-Eintrag verhindert unter Umständen die Zertifikatsausstellung.
* **Wechselnde IP:** beim Router einen DynDNS-Dienst einrichten und
  `email-agent.markb.de` als CNAME darauf zeigen lassen.
* **Portfreigabe:** TCP 80 und 443 vom Router auf den Windows-PC weiterleiten.
  Für den PC eine feste lokale IP bzw. DHCP-Reservierung vergeben.
* **Ports 8080 und 2024 bleiben intern** und werden nicht freigegeben.

Danach `https://email-agent.markb.de` öffnen, Benutzername `mark` und das
gewählte Passwort. Caddy holt und erneuert das Zertifikat selbst; der erste
Abruf kann eine Minute dauern.

## 6. Prüfen, Logs, Updates

```powershell
Get-ScheduledTask -TaskPath '\EmailAgent\' | Get-ScheduledTaskInfo
Invoke-RestMethod http://127.0.0.1:8080/api/status
Get-Content .\.inbox-logs\inbox.log -Tail 40 -Wait
```

`connected: true` bestätigt den Agenten, `error: null` nach dem ersten Abruf
den Postfachzugriff. Logs liegen in `.inbox-logs` (`agent.log`, `inbox.log`,
`caddy.log`) und werden ab 5 MB einmal rotiert.

Update:

```powershell
Get-ScheduledTask -TaskPath '\EmailAgent\' | Stop-ScheduledTask
git pull --ff-only
uv sync --frozen
Get-ScheduledTask -TaskPath '\EmailAgent\' | Start-ScheduledTask
```

Entfernen (Zugangsdaten, Datenbank und Logs bleiben):

```powershell
.\deploy\windows\Uninstall-EmailAgent.ps1
```

## 7. Grenzen

Verwendet wird der **LangGraph-Entwicklungsserver** mit lokaler Speicherung —
passend für den persönlichen Betrieb, keine produktive Installation mit
Postgres/Redis. Bei einem Absturz kann ein laufender Modell- oder SMTP-Aufruf
abbrechen; vor erneutem Versand das Postfach prüfen.

Sichere `.env`, `.local-inbox.sqlite3` und `.langgraph_api\` geschützt; für eine
konsistente Sicherung vorher beide Aufgaben stoppen.

Die Pi-Variante liegt weiterhin unter [`deploy/pi/README.md`](../pi/README.md).
Der Agent selbst braucht dort wenig Arbeitsspeicher, solange das Modell in der
Cloud läuft (OpenAI oder Ollama Cloud) — knapp wird es erst mit einem lokalen
Modell auf dem Pi. Es darf immer nur eine Instanz laufen: vor einem Wechsel die
Dienste auf dem anderen Gerät stoppen.
