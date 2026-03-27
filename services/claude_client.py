"""AI client using DuckDuckGo AI Chat — no API key needed.

Uses the duckduckgo-search library to access GPT-4o mini, Claude 3 Haiku,
Llama, and Mixtral models for free.
"""

from duckduckgo_search import DDGS

# Available models: "gpt-4o-mini", "claude-3-haiku-20240307", "llama-3.3-70b", "mixtral-8x7b"
DEFAULT_MODEL = "gpt-4o-mini"


def ask_ai(prompt: str, system: str = "", model: str = None) -> str | None:
    """Send a prompt to the AI model and return the text response.

    Args:
        prompt: The user prompt
        system: System instructions (prepended to prompt since DuckDuckGo
                doesn't support system messages separately)
        model: Model to use. Options: "gpt-4o-mini", "claude-3-haiku-20240307",
               "llama-3.3-70b", "mixtral-8x7b"
    """
    model = model or DEFAULT_MODEL

    full_prompt = prompt
    if system:
        full_prompt = f"Instructions: {system}\n\n{prompt}"

    try:
        with DDGS() as ddgs:
            response = ddgs.chat(full_prompt, model=model)
            return response if response else None
    except Exception:
        # Try with a fallback model if primary fails
        if model != "mixtral-8x7b":
            try:
                with DDGS() as ddgs:
                    response = ddgs.chat(full_prompt, model="mixtral-8x7b")
                    return response if response else None
            except Exception:
                pass
        return None
