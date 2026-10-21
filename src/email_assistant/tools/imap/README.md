# IMAP/SMTP Integration (one.com and other providers)

This integration connects the email assistant to a real mailbox over standard
IMAP/SMTP instead of the Gmail API — no OAuth setup required, just your email
address and password. It powers the `email_assistant_hitl_memory_imap` graph.

It was built and tested with **one.com** in mind, but works with any provider
that offers IMAP/SMTP access.

## 1. Configure your credentials

Add the following to the `.env` file in the repository root (see
`.env.example`):

```bash
EMAIL_ADDRESS=you@yourdomain.com
EMAIL_PASSWORD=your_mailbox_password

# one.com servers (defaults — only needed if you use a different provider)
IMAP_HOST=imap.one.com
IMAP_PORT=993
SMTP_HOST=send.one.com
SMTP_PORT=465
SMTP_STARTTLS=false
```

### one.com specifics

- **IMAP**: `imap.one.com`, port `993`, SSL/TLS
- **SMTP**: `send.one.com`, port `465` (SSL) or port `587` with
  `SMTP_STARTTLS=true`
- **Username**: your full email address
- **Password**: your normal mailbox password (one.com does not use app
  passwords). You can manage the mailbox password in the one.com control
  panel under *Email* → your address.

### Other providers

Set `IMAP_HOST`/`SMTP_HOST` (and ports) accordingly. For providers that
require app passwords (e.g. GMX, web.de, iCloud), generate one and use it as
`EMAIL_PASSWORD`.

### Ollama Cloud instead of OpenAI

The IMAP assistant supports direct Ollama Cloud access. Set these values in
`.env` (an OpenAI key is not needed when using this provider):

```dotenv
MODEL_PROVIDER=ollama_cloud
OLLAMA_API_KEY=your_ollama_api_key
OLLAMA_MODEL=gpt-oss:120b
```

Create a key at https://ollama.com/settings/keys. No local Ollama installation
is required. Email content and feedback are sent to the selected model provider.
The selected model must support tool calling. To switch back, set
`MODEL_PROVIDER=openai` and configure `OPENAI_API_KEY` (optionally `OPENAI_MODEL`).

## 2. Test the connection

```bash
python src/email_assistant/tools/imap/test_connection.py
```

This verifies the IMAP and SMTP logins and lists your unread emails from the
last 24 hours.

## 3. Run the assistant on real emails

Start the LangGraph server:

```bash
langgraph dev --config langgraph.imap.json
```

Then ingest recent unread emails into the `email_assistant_hitl_memory_imap`
graph:

```bash
python src/email_assistant/tools/imap/run_ingest.py --minutes-since 120
```

Useful flags:

- `--include-read` — also process emails that are already marked as read
- `--early` — stop after the first email (good for testing)
- `--minutes-since N` — how far back to look (default: 120)

Human-in-the-loop review works exactly like the Gmail version: pending
actions (email drafts, meeting invites, questions) show up in
[Agent Inbox](https://dev.agentinbox.ai/), where you can accept, edit, or
ignore them before anything is sent.

To poll your inbox continuously, run the ingest script on a schedule (e.g.
cron every 10 minutes) or in a loop.

## What the tools do

| Tool | Implementation |
|------|----------------|
| `fetch_emails_tool` | Fetches unread emails via IMAP (`BODY.PEEK`, so nothing is marked as read prematurely) |
| `send_email_tool` | Sends real replies via SMTP with proper `In-Reply-To`/`References` threading and stores a copy in the Sent folder |
| `schedule_meeting_tool` | Sends a real iCalendar (`.ics`) invite email to all attendees |
| `check_calendar_tool` | Plain IMAP accounts have no calendar API, so this reports default working-hours availability |
| `mark_as_read` | Sets the `\Seen` flag via IMAP once the assistant is done with an email |

Emails are threaded using the `Message-ID`, `In-Reply-To`, and `References`
headers, so replies land in the same conversation in your email client and
follow-ups map to the same LangGraph thread.
