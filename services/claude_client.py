"""AI client using Google Gemini API (free tier).

Requires GEMINI_API_KEY environment variable.
Free tier: 15 requests/minute, 1M tokens/day.
"""

import requests
from config import GEMINI_API_KEY

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.0-flash"


def ask_ai(prompt: str, system: str = "", model: str = None) -> str | None:
    """Send a prompt to Gemini and return the text response."""
    if not GEMINI_API_KEY:
        return None

    model = model or DEFAULT_MODEL
    url = f"{GEMINI_API_URL}/{model}:generateContent?key={GEMINI_API_KEY}"

    payload = {"contents": []}

    if system:
        payload["systemInstruction"] = {
            "parts": [{"text": system}]
        }

    payload["contents"].append({
        "role": "user",
        "parts": [{"text": prompt}]
    })

    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text")
        return None
    except Exception:
        return None
