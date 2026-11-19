"""Minimal async client for the Claude Messages API (plain httpx, no SDK)."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from .config import AISettings

log = logging.getLogger(__name__)

API_VERSION = "2026-10-21"


class LLMError(RuntimeError):
    pass


class ClaudeClient:
    def __init__(self, settings: AISettings, api_key: str, base_url: str | None = None,
                 timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        self.model = settings.model
        self.effort = settings.effort
        self.thinking = settings.thinking
        self._key = api_key
        self._url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    def build_body(self, system: str, prompt: str, max_tokens: int) -> dict:
        body = {
            "model": self.model,
            # Thinking tokens count towards max_tokens, so keep headroom even
            # though replies are short; effort is the real cost/latency lever.
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": self.effort},
        }
        if self.thinking == "disabled":
            body["thinking"] = {"type": "disabled"}
        return body

    async def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        """Single-turn completion. Retries once on network errors, 429, 5xx and 529."""
        body = self.build_body(system, prompt, max_tokens)
        for attempt in (1, 2):
            try:
                resp = await self._http.post(self._url, json=body, headers={
                    "x-api-key": self._key,
                    "anthropic-version": API_VERSION,
                })
                resp.raise_for_status()
                return self._text(resp.json())
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                detail = f"HTTP {code}: {exc.response.text[:400]}"
                if attempt == 2 or not (code == 429 or code >= 500):
                    raise LLMError(detail) from exc
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise LLMError(f"network error: {exc}") from exc
            await asyncio.sleep(1.5)
        raise AssertionError("unreachable")

    @staticmethod
    def _text(data: dict) -> str:
        text = "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text").strip()
        if not text:
            # e.g. max_tokens reached while thinking: no text block at all
            raise LLMError(f"no text in response (stop_reason={data.get('stop_reason')})")
        return text

    async def check(self) -> None:
        """Fail fast at startup on a bad key, model name or parameter combination."""
        reply = await self.complete("You are a health check.", "Reply with the word OK.", max_tokens=256)
        log.info("Claude check reply: %r", reply[:20])


def client_from_env(settings: AISettings) -> ClaudeClient:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set, but AI participants are configured or may be needed "
            "to fill empty seats after experiment.max_wait_seconds. Add the key to .env "
            "(see .env.example), or set max_wait_seconds: null and use CONDITION=three_humans."
        )
    return ClaudeClient(settings, key, os.getenv("ANTHROPIC_BASE_URL") or None)
