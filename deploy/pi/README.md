# Raspberry Pi: email-agent.markb.de

Vorbereitet für Raspberry Pi OS **64 Bit**, Python 3.11–3.13 und einen Pi mit
Internetzugang. Die Dienste laufen unter deinem normalen Benutzer. Auf einem
Raspberry Pi 4 (Raspberry Pi OS 64 Bit, aarch64) eingerichtet und dort
geprüft; die Veröffentlichung unter der Domain beschreibt Abschnitt 3.

## 1. Repository und Zugangsdaten

```bash
cd ~
git clone --branch claude/imap-one-com-email-gk8i3s https://github.com/mark-baumann/email-agent.git
cd email-agent
```

Falls bereits geklont: im vorhandenen Checkout auf diesen Branch wechseln und
`git pull --ff-only` ausführen. Die Service-Dateien erwarten `~/email-agent`.

Installiere [uv](https://docs.astral.sh/uv/getting-started/installation/) und dann:

```bash
uv sync --frozen
cp .env.example .env
chmod 600 .env
nano .env
```

Setze die echten Werte für `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `MODEL_PROVIDER`
und den zugehörigen Modell-Key. Für Ollama Cloud: `MODEL_PROVIDER=ollama_cloud`
und `OLLAMA_API_KEY`. Ohne LangSmith-Tracing: `LANGSMITH_TRACING=false`.
Für den Zugriff über die Domain zusätzlich:

```dotenv
INBOX_ALLOWED_HOSTS=127.0.0.1,localhost,email-agent.markb.de
```

Keine `.env`, Passwörter, echten Mail-Exporte oder Importdaten ins Git aufnehmen.

## 2. Dienste einrichten

```bash
mkdir -p ~/.config/systemd/user
cp deploy/pi/email-agent.service deploy/pi/email-inbox.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now email-agent.service email-inbox.service
sudo loginctl enable-linger "$USER"
curl -fsS http://127.0.0.1:${INBOX_PORT:-8080}/api/status
```

Mit gesetztem `INBOX_PASSWORD` braucht `/api/status` die Anmeldung
(`-u mark:PASSWORT`); der LangGraph-Server antwortet unter
`http://127.0.0.1:2024/ok`. Der Start des Agenten dauert rund eine halbe Minute.

`connected: true` bestätigt den Agenten. `error: null` nach dem ersten Abruf
bestätigt den Postfachzugriff. Ein Benutzer-Dienst läuft durch `enable-linger`
auch nach dem SSH-Logout und nach einem Neustart.

```bash
journalctl --user -u email-agent -u email-inbox -f
```

Die UI ruft alle 30 Sekunden ungelesene Mails der letzten 24 Stunden ab.
Für Mails an dich selbst in der UI „Eigene Testmails einbeziehen“ einschalten.
Die Einstellungen werden in `.local-inbox.sqlite3` gespeichert.

## 3. HTTPS und Anmeldung

Zwei Wege. **A** gilt für einen Pi, auf dem schon ein Cloudflare-Tunnel läuft
(so ist `email-agent.markb.de` eingerichtet); **B** für einen Pi, der die Ports
80/443 selbst aus dem Router bekommt.

### A. Hinter einem vorhandenen Cloudflare-Tunnel

Der Tunnel läuft als Container und erreicht Dienste auf dem Pi über das
Gateway des Docker-Netzes (`docker network inspect <netz>`, dort `Gateway`,
z. B. `172.19.0.1`). Die UI muss dafür über Loopback hinaus lauschen und wird
dann von ihrer eigenen Anmeldung geschützt — in `.env`:

```dotenv
INBOX_HOST=0.0.0.0
INBOX_PORT=8081
INBOX_USER=mark
INBOX_PASSWORD=<langes Passwort>
INBOX_ALLOWED_HOSTS=127.0.0.1,localhost,172.19.0.1,email-agent.markb.de
```

`INBOX_PORT` nur frei wählen, wenn 8080 schon belegt ist (`ss -ltn`); auf
diesem Pi hält Traefik den Port. Ohne `INBOX_PASSWORD` startet die UI bei
`INBOX_HOST` ≠ Loopback absichtlich nicht. Prüfen:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/            # 401
curl -s -o /dev/null -w '%{http_code}\n' -u mark:PASSWORT http://127.0.0.1:8081/   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/api/health  # 200, ohne Anmeldung
```

Im Cloudflare-Tunnel dann einen Public Hostname `email-agent.markb.de` →
`HTTP` → `172.19.0.1:8081` anlegen; Cloudflare erzeugt den DNS-Eintrag und das
Zertifikat. Bei einem per Token verwalteten Tunnel geschieht das im
Zero-Trust-Dashboard oder über die API — die Datei `cloudflared/config.yml`
auf dem Pi wird dabei **nicht** gelesen. Ports 8081 und 2024 bleiben intern;
nichts im Router freigeben. `/api/health` bleibt offen, damit Tunnel- und
Container-Prüfungen kein Passwort brauchen.

### B. Caddy direkt auf dem Pi

Installiere Caddy nach der [offiziellen Debian/Raspbian-Anleitung](https://caddyserver.com/docs/install#debian-ubuntu-raspbian).
Erzeuge auf dem Pi einen Passwort-Hash:

```bash
caddy hash-password
```

Füge den Site-Block aus `deploy/pi/Caddyfile` zu `/etc/caddy/Caddyfile` hinzu.
Ersetze `REPLACE_WITH_BCRYPT_HASH` durch den erzeugten Hash. Falls bereits
andere Domains auf dem Pi laufen, deren Blöcke beibehalten. Caddy ab Version 2.8
verwendet `basic_auth`; bei älteren Versionen Caddy zuerst aktualisieren.

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

DNS: `email-agent.markb.de` muss auf den öffentlichen Anschluss zeigen, der den
Pi erreicht. Bei einem Pi hinter dem Router TCP 80 und 443 zum Pi weiterleiten.
Nur passende A/AAAA-Einträge verwenden; ein falscher IPv6-Eintrag verhindert
unter Umständen die Zertifikatsausstellung. Falls bereits ein Reverse Proxy
oder Tunnel existiert, dort HTTPS und Anmeldung entsprechend einrichten.
Ports **8080 und 2024 bleiben intern**; nicht im Router freigeben.

Dann **https://email-agent.markb.de** öffnen. Benutzername: `mark`, Passwort:
das beim Hashen gewählte Passwort. Die Anmeldung schützt auch die E-Mail- und
Input-Export-APIs. Caddy stellt und erneuert das HTTPS-Zertifikat.

## 4. Input-YAML / LangSmith Studio

Eine E-Mail öffnen → „Input für LangSmith / Studio“ → YAML herunterladen oder
„JSON für Studio kopieren“. Das exportierte Objekt enthält genau
`email_input` mit `from`, `to`, `subject`, `body`, `id`. Keine API-Keys oder
internen Zustände. Im Studio den Graphen `email_assistant_hitl_memory_imap`
wählen und unter **View Raw** das JSON einfügen. YAML ist das zusätzliche
Exportformat; der Studio-Roheditor erwartet JSON.

Studio vom eigenen Rechner mit dem Pi verbinden, ohne die Agent-API öffentlich
zu machen (auf dem eigenen Rechner ausführen, `USER`/`PI` ersetzen):

```bash
ssh -N -L 2024:127.0.0.1:2024 USER@PI
```

Auf deinem Rechner darf dann kein anderer Dienst Port 2024 belegen. Anschließend
[Studio öffnen](https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024).
Tracing nach LangSmith bleibt optional und benötigt einen gültigen Key in `.env`.

## 5. Updates und Grenzen

Vor dem Wechsel auf den Pi den Abruf auf dem Windows-Rechner ausschalten oder
die lokale UI beenden, damit nicht zwei unabhängige Instanzen Mails bearbeiten.

```bash
cd ~/email-agent
git pull --ff-only
uv sync --frozen
systemctl --user restart email-agent.service email-inbox.service
```

Sichere `.env`, `.local-inbox.sqlite3` und `.langgraph_api/` geschützt. Für eine
konsistente Sicherung beide Benutzer-Dienste vorher stoppen und danach starten.
Keine laufende zweite Instanz auf derselben Datenbank starten.

Diese Konfiguration verwendet den vorhandenen **LangGraph-Entwicklungsserver**
mit lokaler Speicherung. Sie ist für den persönlichen Pi-Betrieb vorbereitet,
keine produktive LangSmith-Deployment-Installation mit Postgres/Redis. Bei
Abstürzen kann ein gerade laufender Modell- oder SMTP-Aufruf unterbrochen
werden. Vor einem erneuten Versand gesendete Nachrichten im Postfach prüfen.
