"""Model configuration for the IMAP assistant."""

import os

from langchain_openai import ChatOpenAI


def create_chat_model() -> ChatOpenAI:
    """Create an OpenAI or directly hosted Ollama Cloud chat model."""
    provider = os.getenv("MODEL_PROVIDER", "openai").strip().lower()
    if provider == "ollama_cloud":
        api_key = os.getenv("OLLAMA_API_KEY", "").strip()
        if not api_key or api_key == "your_ollama_api_key":
            raise ValueError("Set OLLAMA_API_KEY in .env to use Ollama Cloud.")
        return ChatOpenAI(
            model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
            base_url="https://ollama.com/v1",
            api_key=api_key,
            temperature=0,
            timeout=120,
            use_responses_api=False,
        )
    if provider == "openai":
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1"), temperature=0,
        )
    raise ValueError("MODEL_PROVIDER must be openai or ollama_cloud.")
