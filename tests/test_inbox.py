"""Verify polling deduplication and the human approval boundary without sending mail."""

import asyncio
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from starlette.testclient import TestClient

from email_assistant.inbox import Inbox, TOKEN, app, pending, studio_input


def test_poll_deduplicates_messages_and_recovers_existing_runs():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            inbox = Inbox(Path(directory) / "inbox.sqlite3")
            created = []

            async def api(method, path, **kwargs):
                if method == "GET" and path.endswith("/runs"):
                    return []
                if method == "POST" and path.endswith("/runs"):
                    created.append(kwargs["json"])
                return {}

            inbox.api = api
            mail = {"id": "<test>", "from_email": "sender@example.org", "to_email": "me@example.org",
                    "subject": "Question", "page_content": "Please reply"}
            try:
                with patch("email_assistant.inbox.load_imap_config", return_value=SimpleNamespace(email_address="me@example.org")), \
                     patch("email_assistant.inbox.fetch_group_emails", return_value=[mail, mail]):
                    assert await inbox.sync() == 1
                    assert await inbox.sync() == 0
                assert len(created) == 1
                assert created[0]["input"]["email_input"]["id"] == "<test>"
                # Losing the local receipt must not create another run either.
                with inbox.db() as db:
                    db.execute("DELETE FROM imported")
                original = inbox.api

                async def recovered(method, path, **kwargs):
                    if method == "GET" and path.endswith("/runs"):
                        return [{"status": "interrupted"}]
                    return await original(method, path, **kwargs)

                inbox.api = recovered
                with patch("email_assistant.inbox.load_imap_config", return_value=SimpleNamespace(email_address="me@example.org")), \
                     patch("email_assistant.inbox.fetch_group_emails", return_value=[mail]):
                    await inbox.sync()
                assert len(created) == 1
            finally:
                await inbox.client.aclose()
    asyncio.run(scenario())


def test_approval_requires_token_current_checkpoint_and_allowed_action():
    calls = []
    state = {"checkpoint": {"checkpoint_id": "current"}, "tasks": [{"interrupts": [{
        "id": "approval", "value": [{"action_request": {"action": "Question", "args": {}},
                                      "config": {"allow_respond": True, "allow_accept": False}}],
    }]}]}

    async def api(method, path, **kwargs):
        if method == "GET":
            return state
        calls.append(kwargs["json"])
        return {"status": "pending"}

    app.state.inbox = SimpleNamespace(api=api, actions=asyncio.Lock())
    client = TestClient(app)
    body = {"thread": "fc78ad6b-5aea-db24-3d19-af6872303f91", "checkpoint_id": "current",
            "interrupt_id": "approval", "response": {"type": "accept", "args": None}}
    assert client.post("/api/respond", json=body).status_code == 403
    headers = {"x-inbox-token": TOKEN}
    assert client.post("/api/respond", headers=headers, json={**body, "checkpoint_id": "old"}).status_code == 409
    assert client.post("/api/respond", headers=headers, json=body).status_code == 400
    assert not calls
    body["response"] = {"type": "response", "args": "Please draft a reply"}
    assert client.post("/api/respond", headers=headers, json=body).status_code == 200
    assert calls[0]["command"]["resume"] == {"approval": [body["response"]]}
    assert calls[0]["multitask_strategy"] == "reject"


def test_pending_and_email_html_are_not_executed_in_the_ui():
    assert pending({"tasks": []}) == []
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert ".innerHTML" not in response.text
    assert "__CSRF_TOKEN__" not in response.text


def test_settings_survive_restart():
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inbox.sqlite3"
            first = Inbox(path)
            first.save_settings({"auto": False, "include_self": True})
            await first.client.aclose()
            second = Inbox(path)
            assert second.auto is False
            assert second.include_self is True
            await second.client.aclose()
    asyncio.run(scenario())


def test_studio_exports_preserve_original_input_without_internal_state():
    values = {"email_input": {"from": "Sender <a@example.org>", "to": "b@example.org",
                              "subject": "Frage: Termin?", "body": "Grüße!\nJa: bitte\n<script>test</script>",
                              "id": "<id>", "internal": "not exported"},
              "messages": [{"content": "private state"}], "api_key": "not exported"}

    async def api(method, path, **kwargs):
        return {"values": values}

    app.state.inbox = SimpleNamespace(api=api)
    client = TestClient(app)
    thread = "fc78ad6b-5aea-db24-3d19-af6872303f91"
    exported = studio_input(values)
    yaml_response = client.get(f"/api/threads/{thread}/input.yaml")
    json_response = client.get(f"/api/threads/{thread}/input.json")
    assert yaml_response.status_code == json_response.status_code == 200
    assert yaml.safe_load(yaml_response.text) == json.loads(json_response.text) == exported
    assert exported["email_input"]["body"] == values["email_input"]["body"]
    assert "attachment" in yaml_response.headers["content-disposition"]
    assert yaml_response.headers["cache-control"] == "no-store"
    assert "not exported" not in yaml_response.text
