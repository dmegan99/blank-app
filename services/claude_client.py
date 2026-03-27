"""AI client using DuckDuckGo AI Chat — no API key needed.

Uses the duckai library to access GPT-4o mini, Claude 3 Haiku,
Llama 3.3, and Mixtral models for free.
"""

from duckai import DuckAI

# Available models: "gpt-4o-mini", "claude-3-haiku", "llama-3.3-70b", "mixtral-8x7b"
DEFAULT_MODEL = "gpt-4o-mini"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = DuckAI()
    return _client


def ask_ai(prompt: str, system: str = "", model: str = None) -> str | None:
    """Send a prompt to the AI model and return the text response.

    Args:
        prompt: The user prompt
        system: System instructions (prepended to prompt since DuckDuckGo
                doesn't support system messages separately)
        model: Model to use. Options: "gpt-4o-mini", "claude-3-haiku",
               "llama-3.3-70b", "mixtral-8x7b"
    """
    client = _get_client()
    model = model or DEFAULT_MODEL

    # DuckDuckGo AI Chat doesn't have a separate system message,
    # so we prepend it to the prompt
    full_prompt = prompt
    if system:
        full_prompt = f"Instructions: {system}\n\n{prompt}"

    try:
        response = client.chat(full_prompt, model=model)
        return response if response else None
    except Exception as e:
        # Try with a fallback model if primary fails
        if model != "mixtral-8x7b":
            try:
                response = client.chat(full_prompt, model="mixtral-8x7b")
                return response if response else None
            except Exception:
                pass
        return None
