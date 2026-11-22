"""LLM provider abstraction: Gemini, OpenAI, Groq (OpenAI-compatible) or an offline fallback."""
from __future__ import annotations

import json
import logging
import re
import time

from .config import Settings

log = logging.getLogger(__name__)

DEFAULT_MODELS = {"gemini": "gemini-2.5-flash", "openai": "gpt-4o-mini", "groq": "llama-3.3-70b-versatile"}


class LLMClient:
    def __init__(self, settings: Settings):
        self.provider = settings.llm_provider
        self.model = settings.llm_model or DEFAULT_MODELS.get(self.provider, "offline-extractive")
        self._client = None
        if self.provider == "gemini":
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY not set (or use LLM_PROVIDER=offline)")
            from google import genai

            self._client = genai.Client(api_key=settings.gemini_api_key)
        elif self.provider in ("openai", "groq"):
            from openai import OpenAI

            key = settings.openai_api_key if self.provider == "openai" else settings.groq_api_key
            if not key:
                raise RuntimeError(f"{self.provider.upper()}_API_KEY not set (or use LLM_PROVIDER=offline)")
            base = "https://api.groq.com/openai/v1" if self.provider == "groq" else None
            self._client = OpenAI(api_key=key, base_url=base)
        elif self.provider != "offline":
            raise ValueError(f"Unknown LLM_PROVIDER '{self.provider}'")

    @property
    def is_offline(self) -> bool:
        return self.provider == "offline"

    def complete_json(self, system: str, user: str, retries: int = 2) -> dict:
        last = None
        for attempt in range(retries + 1):
            try:
                raw = self._call(system, user)
                return parse_json(raw)
            except Exception as e:
                last = e
                log.warning("LLM call failed (attempt %d): %s", attempt + 1, e)
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"LLM failed after retries: {last}")

    def _call(self, system: str, user: str) -> str:
        if self.provider == "gemini":
            from google.genai import types

            resp = self._client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(system_instruction=system, temperature=0.2,
                                                   response_mime_type="application/json"),
            )
            return resp.text
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise
        return json.loads(m.group(0))
