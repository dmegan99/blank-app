"""AI client using Google Gemini API (free tier with billing enabled).

Requires GEMINI_API_KEY environment variable.
Free tier: 15 requests/minute, 1M tokens/day.
"""

import logging
import requests
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"


def ask_ai(prompt: str, system: str = "", model: str = None) -> str | None:
    """Send a prompt to Gemini and return the text response."""
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set")
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
        if resp.status_code != 200:
            logger.error(f"Gemini API error {resp.status_code}: {resp.text[:500]}")
            return f"[API Error {resp.status_code}]: {resp.text[:200]}"
        data = resp.json()

        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text")

        logger.error(f"Gemini returned no candidates: {data}")
        return None
    except Exception as e:
        logger.error(f"Gemini request failed: {e}")
        return f"[Error]: {str(e)[:200]}"
