"""Test doubles and helpers shared by the test modules."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.session import Session, SessionManager

# Payload fragments that would reveal who is human and who is AI.
LEAK_MARKERS = ['"kind"', '"sender_type"', '"voter_type"', '"backfill"', '"personality',
                '"composition"', '"condition"', '"type": "ai"', '"type": "human"']


class FakeStore:
    """In-memory stand-in for app.db.Store with the same async interface."""

    def __init__(self, *_args, **_kwargs):
        self.docs: dict[str, dict] = {}

    async def connect(self, attempts: int = 1) -> None:
        pass

    async def close(self) -> None:
        pass

    async def create_session(self, doc):
        self.docs[doc["_id"]] = copy.deepcopy(doc)

    async def push(self, session_id, array, item):
        self.docs[session_id][array].append(copy.deepcopy(item))

    async def set(self, session_id, fields):
        self.docs[session_id].update(copy.deepcopy(fields))

    def doc_for(self, session: Session) -> dict:
        return self.docs[session.id]


class FakeLLM:
    """Stands in for ClaudeClient.

    `chat` / `vote` are either a fixed reply, an Exception to raise, or a
    callable (system, prompt) -> reply. Every call is recorded.
    """

    def __init__(self, chat="hi everyone", vote="A"):
        self.chat = chat
        self.vote = vote
        self.calls: list[dict] = []

    async def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        kind = "vote" if "exactly one letter" in prompt else "chat"
        self.calls.append({"kind": kind, "system": system, "prompt": prompt})
        await asyncio.sleep(0)
        reply = getattr(self, kind)
        if callable(reply):
            reply = reply(system, prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def prompts(self, kind: str) -> list[dict]:
        return [c for c in self.calls if c["kind"] == kind]

    async def check(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


class FakeWS:
    """Records what the server sends; payloads are round-tripped through JSON
    so anything that is not JSON-serialisable fails the test."""

    def __init__(self):
        self.sent: list[dict] = []
        self.close_code: int | None = None

    async def send_json(self, payload):
        self.sent.append(json.loads(json.dumps(payload)))

    async def close(self, code: int = 1000):
        self.close_code = code

    def of(self, kind: str) -> list[dict]:
        return [m for m in self.sent if m["type"] == kind]

    @property
    def state(self) -> dict | None:
        states = self.of("state")
        return states[-1] if states else None

    @property
    def errors(self) -> list[str]:
        return [m["message"] for m in self.of("error")]


@dataclass
class Human:
    """A connected human participant, driven the way the WebSocket endpoint does."""
    manager: SessionManager
    session: Session
    p: object
    ws: FakeWS

    @property
    def state(self) -> dict:
        return self.ws.state

    @property
    def label(self) -> str:
        return self.state["you"]

    async def chat(self, text: str):
        await self.session.handle(self.p, {"type": "chat", "text": text})

    async def vote(self, target: str):
        await self.session.handle(self.p, {"type": "vote", "target": target})

    async def leave(self):
        await self.manager.disconnect(self.session, self.p, self.ws)

    async def wait_phase(self, phase: str, round_no: int | None = None, timeout: float = 5.0):
        await wait_until(lambda: self.state["phase"] == phase
                         and (round_no is None or self.state["round"] == round_no), timeout)
        return self.state


async def join(manager: SessionManager, pid: str | None = None) -> Human:
    """Same steps as app.main.websocket_endpoint on connect."""
    ws = FakeWS()
    session, p = await manager.connect(ws, pid)
    await ws.send_json({"type": "welcome", "participant_id": p.pid})
    await session.send_state(p)
    return Human(manager, session, p, ws)


async def wait_until(predicate, timeout: float = 5.0, step: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(step)
    raise AssertionError(f"condition not met within {timeout}s")


@asynccontextmanager
async def running(cfg, llm: FakeLLM | None = None):
    store = FakeStore()
    manager = SessionManager(cfg, store, llm)
    try:
        yield manager, store
    finally:
        await manager.shutdown()


def assert_blind(*payload_lists: list[dict]) -> None:
    """Nothing sent to a browser may reveal participant types or the condition."""
    for payloads in payload_lists:
        for m in payloads:
            dump = json.dumps(m)
            for marker in LEAK_MARKERS:
                assert marker not in dump, f"{marker} leaked in {dump[:300]}"
