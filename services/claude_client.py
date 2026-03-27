"""AI client using Groq API (free tier).

Requires GROQ_API_KEY environment variable.
Free tier: 30 RPM, 14,400 requests/day, no credit card needed.
Uses Llama 3.3 70B — very capable for financial analysis.
"""

import logging
import requests
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"


def ask_ai(prompt: str, system: str = "", model: str = None) -> str | None:
    """Send a prompt to Groq and return the text response."""
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY is not set")
        return None

    model = model or DEFAULT_MODEL

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 4000,
        "temperature": 0.7,
    }

    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            logger.error(f"Groq API error {resp.status_code}: {resp.text[:500]}")
            return f"[API Error {resp.status_code}]: {resp.text[:200]}"
        data = resp.json()

        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content")

        logger.error(f"Groq returned no choices: {data}")
        return None
    except Exception as e:
        logger.error(f"Groq request failed: {e}")
        return f"[Error]: {str(e)[:200]}"
