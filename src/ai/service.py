"""
Unified AI service for JobBot.
Supports Groq and Gemini — both offer free tiers.

Groq:   https://console.groq.com  (free, fast, open models)
Gemini: https://aistudio.google.com (free tier with Gemini Flash)
"""
from __future__ import annotations

import json
import re
from typing import Optional

from src.utils import log


# ---------------------------------------------------------------------------
# Model catalogues shown in the settings UI
# ---------------------------------------------------------------------------

GROQ_MODELS = [
    {"id": "llama-3.3-70b-versatile",  "label": "Llama 3.3 70B — Best quality",   "context": "128k"},
    {"id": "llama-3.1-8b-instant",     "label": "Llama 3.1 8B — Fastest",         "context": "128k"},
    {"id": "mixtral-8x7b-32768",       "label": "Mixtral 8x7B — Balanced",        "context": "32k"},
    {"id": "gemma2-9b-it",             "label": "Gemma 2 9B — Lightweight",       "context": "8k"},
]

GEMINI_MODELS = [
    {"id": "gemini-2.0-flash",         "label": "Gemini 2.0 Flash — Recommended", "context": "1M"},
    {"id": "gemini-1.5-flash",         "label": "Gemini 1.5 Flash — Fast",        "context": "1M"},
    {"id": "gemini-1.5-pro",           "label": "Gemini 1.5 Pro — Most capable",  "context": "2M"},
]

DEFAULT_MODEL = {
    "groq":   "llama-3.3-70b-versatile",
    "gemini": "gemini-2.0-flash",
}


# ---------------------------------------------------------------------------
# Settings helper
# ---------------------------------------------------------------------------

def get_user_ai_settings(username: str) -> dict:
    """Return AI settings dict for a user. Safe — never raises."""
    try:
        from src.database import SessionLocal, UserSettings
        session = SessionLocal()
        try:
            row = session.query(UserSettings).filter_by(username=username).first()
            if not row:
                return {"provider": "groq", "api_key": "", "model": DEFAULT_MODEL["groq"]}
            provider = row.ai_provider or "groq"
            return {
                "provider": provider,
                "api_key":  row.ai_api_key or "",
                "model":    row.ai_model or DEFAULT_MODEL.get(provider, DEFAULT_MODEL["groq"]),
            }
        finally:
            session.close()
    except Exception as e:
        log.warning(f"Could not load AI settings for {username}: {e}")
        return {"provider": "groq", "api_key": "", "model": DEFAULT_MODEL["groq"]}


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------

class AIService:
    """Provider-agnostic wrapper for Groq and Gemini."""

    def __init__(self, provider: str, api_key: str, model: Optional[str] = None):
        self.provider = provider.lower().strip()
        self.api_key  = api_key.strip() if api_key else ""
        self.model    = (model or DEFAULT_MODEL.get(self.provider, "")).strip()

    # -- Constructors --------------------------------------------------------

    @classmethod
    def for_user(cls, username: str) -> "AIService":
        """Build an AIService from a user's saved settings."""
        s = get_user_ai_settings(username)
        return cls(provider=s["provider"], api_key=s["api_key"], model=s["model"])

    # -- Validation ----------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def require_configured(self):
        if not self.is_configured():
            raise ValueError(
                f"No API key set for {self.provider}. "
                "Open AI Settings (⚡ button in nav) to add your key."
            )

    # -- Core generation -----------------------------------------------------

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1500,
    ) -> str:
        """Generate text. Returns the response string."""
        self.require_configured()
        if self.provider == "groq":
            return self._groq(prompt, system, max_tokens)
        elif self.provider == "gemini":
            return self._gemini(prompt, system, max_tokens)
        else:
            raise ValueError(f"Unsupported AI provider: {self.provider!r}")

    def generate_json(
        self,
        prompt: str,
        system: Optional[str] = None,
    ) -> dict | list:
        """Generate and parse a JSON response.  Strips markdown fences."""
        json_hint = "Return ONLY valid JSON — no markdown, no code fences, no extra text."
        combined_system = ((system or "") + "\n" + json_hint).strip()
        raw = self.generate(prompt, combined_system, max_tokens=2000)
        # Strip ```json ... ``` or ``` ... ``` fences
        raw = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip(), flags=re.IGNORECASE)
        raw = re.sub(r"\n?```\s*$", "", raw.strip())
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError as e:
            log.error(f"JSON parse failed. Raw response:\n{raw[:500]}")
            raise ValueError(f"AI returned invalid JSON: {e}") from e

    # -- Provider implementations --------------------------------------------

    def _groq(self, prompt: str, system: Optional[str], max_tokens: int) -> str:
        try:
            from groq import Groq
        except ImportError:
            raise ImportError("groq package not installed. Run: pip install groq")

        client = Groq(api_key=self.api_key)
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.35,
        )
        return resp.choices[0].message.content.strip()

    def _gemini(self, prompt: str, system: Optional[str], max_tokens: int) -> str:
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            )

        genai.configure(api_key=self.api_key)
        cfg = genai.GenerationConfig(max_output_tokens=max_tokens, temperature=0.35)
        model = genai.GenerativeModel(
            self.model,
            system_instruction=system or "",
        )
        response = model.generate_content(
            prompt,
            generation_config=cfg,
        )
        return response.text.strip()
