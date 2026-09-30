"""Async client for Jev's Decisions API, served through OpenRouter.

Reference: https://openrouter.ai/docs/api/api-reference/alphadecisions

Endpoint: POST {JEV_BASE_URL}
  Authorization: Bearer $OPENROUTER_API_KEY
  body: {
    "model": "typesafe/jev-1.13",
    "state":  {...},              # application context to evaluate
    "questions": { <name>: { "type": "noul"|"choice"|"score", ... } }
  }

Response: { "answers": { <name>: <typed answer> }, "usage": {...} }

The client returns the raw ``answers`` dict; parsing thresholds live in
``decider``. Every question in one request is answered in parallel, so adding
independent questions costs only input tokens, not added latency.
"""
from __future__ import annotations

import logging

import httpx

from config import get_settings

log = logging.getLogger("jev")


class JevError(Exception):
    """Raised when the Jev call fails outright (network / auth / 4xx-5xx)."""


class JevClient:
    """Thin async wrapper around the OpenRouter Decisions API."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.JEV_BASE_URL
        self._model = settings.JEV_MODEL
        self._api_key = settings.OPENROUTER_API_KEY
        self._timeout = settings.JEV_TIMEOUT_S

    @property
    def enabled(self) -> bool:
        settings = get_settings()
        return bool(settings.JEV_ENABLED and settings.OPENROUTER_API_KEY)

    async def decide(self, state: dict, questions: dict) -> dict:
        """POST a `state` + `questions` payload and return Jev's `answers`."""
        settings = get_settings()
        if not settings.JEV_ENABLED:
            raise JevError("JEV_ENABLED=false")
        if not self._api_key:
            raise JevError("OPENROUTER_API_KEY not set")

        payload = {
            "model": self._model,
            "state": state,
            "questions": questions,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(
                    self._base_url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.HTTPError as exc:  # network / timeout / connect
                raise JevError(f"Jev request failed: {exc}") from exc

        if resp.status_code != 200:
            raise JevError(
                f"Jev returned {resp.status_code}: {resp.text[:300]}"
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise JevError("Jev returned a non-JSON body") from exc

        answers = body.get("answers")
        if not isinstance(answers, dict):
            raise JevError(f"Jev response missing 'answers': {body!r}")
        return answers