"""Verify provider routing and Ollama tool-call compatibility without a network."""

import json

import httpx
import pytest
from openai import OpenAI

from email_assistant.models import create_chat_model
from email_assistant.schemas import RouterSchema


def test_openai_default(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert create_chat_model().model_name == "gpt-4.1"


def test_ollama_structured_tool_call(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "ollama_cloud")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def respond(request):
        assert str(request.url) == "https://ollama.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-ollama"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-oss:120b"
        assert payload["tools"][0]["function"]["name"] == "RouterSchema"
        assert "response_format" not in payload
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": "gpt-oss:120b", "choices": [{
                "index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": "", "tool_calls": [{
                        "id": "call-test", "type": "function", "function": {
                            "name": "RouterSchema", "arguments": json.dumps({
                                "reasoning": "A question needs a reply.",
                                "classification": "respond",
                            }),
                        },
                    }],
                },
            }],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = create_chat_model().model_copy(update={"client": OpenAI(
            api_key="test-ollama", base_url="https://ollama.com/v1",
            http_client=client,
        ).chat.completions})
        result = model.with_structured_output(
            RouterSchema, method="function_calling",
        ).invoke("Can you reply?")
    assert result.classification == "respond"


@pytest.mark.parametrize("key", ["", "your_ollama_api_key"])
def test_ollama_requires_key(monkeypatch, key):
    monkeypatch.setenv("MODEL_PROVIDER", "ollama_cloud")
    monkeypatch.setenv("OLLAMA_API_KEY", key)
    with pytest.raises(ValueError, match="OLLAMA_API_KEY"):
        create_chat_model()


def test_unknown_provider(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "invalid")
    with pytest.raises(ValueError, match="MODEL_PROVIDER"):
        create_chat_model()
