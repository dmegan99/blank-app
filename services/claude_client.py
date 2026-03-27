"""Anthropic Claude API client for AI-powered commands."""

import anthropic
from config import ANTHROPIC_API_KEY

_client = None


def _get_client():
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            return None
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def ask_claude(prompt: str, system: str = "", max_tokens: int = 4000, model: str = "claude-opus-4-6") -> str | None:
    """Send a prompt to Claude and return the text response."""
    client = _get_client()
    if not client:
        return None

    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)
    if response.content:
        return response.content[0].text
    return None
