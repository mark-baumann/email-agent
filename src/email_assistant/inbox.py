"""Local inbox UI and IMAP polling for the existing LangGraph assistant.

Run with: python -m email_assistant.inbox
"""

import asyncio
import contextlib
import html
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn
import yaml
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from email_assistant.tools.imap.imap_tools import fetch_group_emails, load_imap_config

load_dotenv()
GRAPH = "email_assistant_hitl_memory_imap"
API = os.getenv("INBOX_AGENT_URL", "http://127.0.0.1:2024")
TOKEN = secrets.token_urlsafe(32)
DATABASE = Path(os.getenv("INBOX_DATABASE", ".local-inbox.sqlite3"))


def studio_input(values):
    """Export exactly the graph input, excluding messages, credentials and run metadata."""
    mail = values.get("email_input")
    if not isinstance(mail, dict):
        raise ValueError("Für diesen Vorgang ist noch kein E-Mail-Input verfügbar.")
    return {"email_input": {key: mail.get(key, "") for key in ("from", "to", "subject", "body", "id")}}


class Inbox:
    def __init__(self, database=DATABASE):
        self.database = database
        self.lock = asyncio.Lock()
        self.actions = asyncio.Lock()
        self.auto = True
        self.include_self = False
        self.last_sync = None
        self.error = None
        self.imported = 0
        self.client = httpx.AsyncClient(base_url=API, timeout=30)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS imported (id TEXT PRIMARY KEY, thread TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for key, value in db.execute("SELECT key, value FROM settings"):
                if key in ("auto", "include_self"):
                    setattr(self, key, json.loads(value))

    def save_settings(self, changes):
        if any(key not in ("auto", "include_self") or not isinstance(value, bool)
               for key, value in changes.items()):
            raise ValueError("Ungültige Einstellung")
        with self.db() as db:
            for key, value in changes.items():
                db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
                setattr(self, key, value)

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(self.database)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    async def api(self, method, path, **kwargs):
        result = await self.client.request(method, path, **kwargs)
        result.raise_for_status()
        return result.json()

    async def sync(self):
        async with self.lock:
            self.error = None
            count = 0
            try:
                await self.api("GET", "/ok")
                config = load_imap_config()
                emails = await asyncio.to_thread(
                    lambda: list(fetch_group_emails(
                        minutes_since=24 * 60, skip_filters=self.include_self,
                        config=config,
                    ))
                )
                for mail in emails:
                    if mail.get("user_respond"):
                        continue
                    key = config.email_address.lower() + ":" + mail["id"]
                    with self.db() as db:
                        if db.execute("SELECT 1 FROM imported WHERE id=?", (key,)).fetchone():
                            continue
                    # Each message gets one thread. Never overwrite a pending draft.
                    thread = str(uuid.uuid5(uuid.NAMESPACE_URL, "local-inbox:" + key))
                    await self.api("POST", "/threads", json={
                        "thread_id": thread, "if_exists": "do_nothing",
                        "metadata": {"source": "local-inbox", "email_id": mail["id"]},
                    })
                    runs = await self.api("GET", f"/threads/{thread}/runs")
                    # Recover if the process stopped between creating a run and saving the receipt.
                    if not runs:
                        await self.api("POST", f"/threads/{thread}/runs", json={
                            "assistant_id": GRAPH,
                            "input": {"email_input": {
                                "from": mail["from_email"], "to": mail["to_email"],
                                "subject": mail["subject"], "body": mail["page_content"],
                                "id": mail["id"],
                            }},
                            "multitask_strategy": "reject",
                        })
                    with self.db() as db:
                        db.execute("INSERT OR IGNORE INTO imported VALUES (?, ?)", (key, thread))
                    count += 1
                self.imported = count
                self.last_sync = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                self.error = str(exc)
                raise
            return count

    async def poll(self):
        while True:
            if self.auto:
                try:
                    await self.sync()
                except Exception:
                    pass  # The error is displayed in the UI; the next poll retries.
            await asyncio.sleep(30)


def pending(state):
    """Return the current interrupt requests with their resume identifiers."""
    result = []
    for task in state.get("tasks", []):
        for item in task.get("interrupts", []):
            value = item.get("value", [])
            for request in value if isinstance(value, list) else [value]:
                result.append({"id": item.get("id"), **request})
    return result


@asynccontextmanager
async def lifespan(app):
    load_dotenv()
    app.state.inbox = Inbox()
    task = asyncio.create_task(app.state.inbox.poll())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await app.state.inbox.client.aclose()


async def home(request):
    page = Path(__file__).with_name("inbox.html").read_text(encoding="utf-8")
    studio = os.getenv("INBOX_STUDIO_URL", "https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024")
    return HTMLResponse(page.replace("__CSRF_TOKEN__", TOKEN).replace("__STUDIO_URL__", html.escape(studio, quote=True)), headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    })


async def status(request):
    inbox = request.app.state.inbox
    connected = False
    try:
        await inbox.api("GET", "/ok")
        connected = True
    except httpx.HTTPError:
        pass
    return JSONResponse({"connected": connected, "auto": inbox.auto,
                         "include_self": inbox.include_self, "last_sync": inbox.last_sync,
                         "syncing": inbox.lock.locked(), "error": inbox.error,
                         "imported": inbox.imported})


async def threads(request):
    inbox = request.app.state.inbox
    rows = await inbox.api("POST", "/threads/search", json={"limit": 100})
    # Only include threads belonging to this email graph (including Studio imports).
    rows = [row for row in rows if row.get("metadata", {}).get("graph_id") == GRAPH
            or row.get("metadata", {}).get("source") == "local-inbox"
            or row.get("values", {}).get("email_input")]
    return JSONResponse(sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True))


async def detail(request):
    inbox = request.app.state.inbox
    thread = str(uuid.UUID(request.path_params["thread"]))
    state, runs = await asyncio.gather(
        inbox.api("GET", f"/threads/{thread}/state"),
        inbox.api("GET", f"/threads/{thread}/runs"),
    )
    exported = studio_input(state["values"]) if state.get("values", {}).get("email_input") else None
    return JSONResponse({"state": state, "pending": pending(state), "runs": runs,
                         "input_yaml": yaml.safe_dump(exported, allow_unicode=True, sort_keys=False) if exported else None,
                         "input_json": json.dumps(exported, ensure_ascii=False, indent=2) if exported else None})


async def export_input(request):
    thread = str(uuid.UUID(request.path_params["thread"]))
    state = await request.app.state.inbox.api("GET", f"/threads/{thread}/state")
    exported = studio_input(state.get("values", {}))
    format_name = request.path_params["format"]
    if format_name == "yaml":
        content = yaml.safe_dump(exported, allow_unicode=True, sort_keys=False)
        media_type = "application/yaml"
    elif format_name == "json":
        content = json.dumps(exported, ensure_ascii=False, indent=2)
        media_type = "application/json"
    else:
        raise ValueError("Unbekanntes Exportformat")
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="email-input-{thread}.{format_name}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


async def mutate(request):
    if not secrets.compare_digest(request.headers.get("x-inbox-token", ""), TOKEN):
        return JSONResponse({"error": "Ungültige Sitzung. Bitte Seite neu laden."}, status_code=403)
    inbox = request.app.state.inbox
    body = await request.json()
    operation = request.path_params["operation"]
    if operation == "settings":
        inbox.save_settings(body)
        return JSONResponse({"ok": True})
    if operation == "sync":
        return JSONResponse({"imported": await inbox.sync()})
    async with inbox.actions:
        return await resume(inbox, operation, body)


async def resume(inbox, operation, body):
    thread = str(uuid.UUID(body["thread"]))
    state = await inbox.api("GET", f"/threads/{thread}/state")
    checkpoint = state.get("checkpoint", {})
    if checkpoint.get("checkpoint_id") != body.get("checkpoint_id"):
        return JSONResponse({"error": "Der Vorgang wurde bereits verändert. Bitte neu laden."}, status_code=409)
    if operation == "retry":
        if pending(state):
            raise ValueError("Bitte zuerst die offene Freigabe bearbeiten.")
        runs = await inbox.api("GET", f"/threads/{thread}/runs")
        if not runs or runs[0]["status"] != "error":
            raise ValueError("Nur fehlgeschlagene Vorgänge können erneut gestartet werden.")
        payload = {"input": {"email_input": state["values"]["email_input"]}}
    elif operation == "respond":
        item = next((item for item in pending(state) if item["id"] == body.get("interrupt_id")), None)
        if not item:
            raise ValueError("Diese Freigabe ist nicht mehr offen.")
        response = body["response"]
        kind = response.get("type")
        flag = {"accept": "allow_accept", "edit": "allow_edit",
                "ignore": "allow_ignore", "response": "allow_respond"}.get(kind)
        if not flag or not item.get("config", {}).get(flag):
            raise ValueError("Diese Aktion ist für die Freigabe nicht erlaubt.")
        if kind == "response" and not str(response.get("args", "")).strip():
            raise ValueError("Bitte Feedback eingeben.")
        if kind == "edit":
            edited = response.get("args", {})
            action = item["action_request"]
            if edited.get("action") != action["action"] or not isinstance(edited.get("args"), dict):
                raise ValueError("Ungültiger Entwurf")
        payload = {"command": {"resume": {item["id"]: [response]}}}
    else:
        raise ValueError("Unbekannte Aktion")
    result = await inbox.api("POST", f"/threads/{thread}/runs", json={
        "assistant_id": GRAPH, "multitask_strategy": "reject",
        "checkpoint_id": checkpoint.get("checkpoint_id"), **payload,
    })
    return JSONResponse(result)


async def api_error(request, exc):
    return JSONResponse({"error": str(exc)}, status_code=502 if isinstance(exc, httpx.HTTPError) else 400)


app = Starlette(lifespan=lifespan, routes=[
    Route("/", home), Route("/api/status", status), Route("/api/threads", threads),
    Route("/api/threads/{thread}/input.{format}", export_input),
    Route("/api/threads/{thread}", detail), Route("/api/{operation}", mutate, methods=["POST"]),
], exception_handlers={httpx.HTTPError: api_error, ValueError: api_error, KeyError: api_error})
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[
    host.strip() for host in os.getenv("INBOX_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("INBOX_PORT", "8080")))
