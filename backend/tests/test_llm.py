"""Request/response handling of the Claude client against a mocked HTTP transport."""

import asyncio
import json

import httpx
import pytest

from app.config import AISettings
from app.llm import API_VERSION, ClaudeClient, LLMError


def run(coro):
    return asyncio.run(coro)


def make_client(handler, **settings):
    return ClaudeClient(AISettings(**settings), "sk-test", transport=httpx.MockTransport(handler))


def test_request_shape_and_text_extraction():
    seen = {}

    def handler(request: httpx.Request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": " hi all "}],
            "stop_reason": "end_turn",
        })

    async def go():
        client = make_client(handler)
        try:
            return await client.complete("sys", "prompt", max_tokens=1024)
        finally:
            await client.aclose()

    assert run(go()) == "hi all"
    body = seen["body"]
    assert body["model"] == "claude-haiku-5-5"
    assert body["system"] == "sys"
    assert body["messages"] == [{"role": "user", "content": "prompt"}]
    assert body["output_config"] == {"effort": "low"}
    assert body["thinking"] == {"type": "disabled"}
    assert "temperature" not in body  # removed in API version 2026-10-21
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["headers"]["anthropic-version"] == API_VERSION


def test_adaptive_thinking_omits_thinking_field():
    body = make_client(lambda r: None, thinking="adaptive", model="claude-sonnet-5-5") \
        .build_body("s", "p", 100)
    assert "thinking" not in body and body["model"] == "claude-sonnet-5-5"


def test_no_text_block_is_an_error():
    handler = lambda r: httpx.Response(200, json={"content": [], "stop_reason": "max_tokens"})  # noqa: E731

    async def go():
        client = make_client(handler)
        try:
            await client.complete("s", "p")
        finally:
            await client.aclose()

    with pytest.raises(LLMError, match="max_tokens"):
        run(go())


def test_bad_request_is_not_retried_and_reports_body():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "thinking.type disabled not supported"}})

    async def go():
        client = make_client(handler)
        try:
            await client.complete("s", "p")
        finally:
            await client.aclose()

    with pytest.raises(LLMError, match="disabled not supported"):
        run(go())
    assert len(calls) == 1


def test_overloaded_is_retried_once():
    responses = iter([httpx.Response(529, text="overloaded"),
                      httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})])

    async def go():
        client = make_client(lambda r: next(responses))
        try:
            return await client.complete("s", "p")
        finally:
            await client.aclose()

    assert run(go()) == "ok"


def test_disabled_thinking_rejected_with_high_effort_in_config():
    with pytest.raises(ValueError):
        AISettings(effort="max", thinking="disabled")
