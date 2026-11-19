"""End-to-end: the real FastAPI app served by uvicorn on a free local port, driven by
WebSocket clients like browser tabs. MongoDB is replaced by an in-memory store and
the Claude API by an httpx mock transport, so the real ClaudeClient request/response
code runs too."""

import asyncio
import json
import random

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect

from app import db, llm
from app.main import app
from helpers import FakeStore, LEAK_MARKERS

pytestmark = pytest.mark.anyio


class FakeClaudeAPI:
    """Answers POST /v1/messages and records every request."""

    def __init__(self):
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((request, body))
        prompt = body["messages"][0]["content"]
        if "exactly one letter" in prompt:
            text = random.choice("ABC")
        elif "health check" in body["system"]:
            text = "OK"
        else:
            text = random.choice(["hey, who wants this?", "i'm up for it", "PASS"])
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}],
                                         "stop_reason": "end_turn"})


class Tab:
    """A browser tab: one WebSocket connection, collecting what the server sends."""

    def __init__(self, port, pid=None):
        self.url = f"ws://127.0.0.1:{port}/ws" + (f"?pid={pid}" if pid else "")
        self.frames: list[dict] = []
        self.pid = pid

    async def __aenter__(self):
        self.ws = await connect(self.url)
        self._reader = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc):
        await self.ws.close()
        self._reader.cancel()

    async def _read(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            self.frames.append(msg)
            if msg["type"] == "welcome":
                self.pid = msg["participant_id"]

    @property
    def state(self):
        states = [f for f in self.frames if f["type"] == "state"]
        return states[-1] if states else None

    async def send(self, **payload):
        await self.ws.send(json.dumps(payload))

    async def wait_phase(self, phase, round_no=None, timeout=10.0):
        for _ in range(int(timeout / 0.02)):
            s = self.state
            if s and s["phase"] == phase and (round_no is None or s["round"] == round_no):
                return s
            await asyncio.sleep(0.02)
        raise AssertionError(f"never reached {phase} {round_no}; last={self.state}")


@pytest.fixture
async def live_server(write_config, monkeypatch):
    """Starts the app for a given condition; yields (port, store, claude_api)."""
    servers = []
    fake_api = FakeClaudeAPI()
    stores = []

    def fake_store(url, name):
        stores.append(FakeStore())
        return stores[-1]

    def fake_client(settings):
        return llm.ClaudeClient(settings, "sk-test", transport=httpx.MockTransport(fake_api))

    monkeypatch.setattr(db, "Store", fake_store)
    monkeypatch.setattr(llm, "client_from_env", fake_client)

    async def start(condition, **experiment):
        monkeypatch.setenv("CONFIG_PATH", str(write_config(condition, **experiment)))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        servers.append((server, task))
        port = server.servers[0].sockets[0].getsockname()[1]
        return port, stores[-1], fake_api

    yield start
    for server, task in servers:
        server.should_exit = True
        await task


def assert_frames_blind(*tabs):
    for tab in tabs:
        for frame in tab.frames:
            dump = json.dumps(frame)
            assert not any(marker in dump for marker in LEAK_MARKERS), dump[:300]


async def test_two_humans_and_one_ai_end_to_end(live_server):
    port, store, claude = await live_server("two_humans_one_ai", discussion_seconds=1.2,
                                            voting_seconds=5)
    async with Tab(port) as a, Tab(port) as b:
        await a.wait_phase("discussion", 1)
        await b.wait_phase("discussion", 1)
        assert a.state["you"] != b.state["you"] and len(a.state["players"]) == 3

        # a third tab lands in a new waiting room, not in the running session
        async with Tab(port) as late:
            assert (await late.wait_phase("waiting"))["you"] is None

        # b reloads mid-discussion and keeps its seat and the history
        await a.send(type="chat", text="before reload")
        await asyncio.sleep(0.2)
        seat, pid = b.state["you"], b.pid
        await b.__aexit__()
        async with Tab(port, pid=pid) as b2:
            state = await b2.wait_phase("discussion", 1)
            assert state["you"] == seat
            assert "before reload" in [m["text"] for m in state["messages"]]

            for r in (1, 2):
                await a.wait_phase("voting", r)
                await a.send(type="vote", target=a.state["you"])
                await b2.send(type="vote", target=a.state["you"])
            final = await a.wait_phase("results")
            assert final["result"]["decision_maker"] in final["players"]
            assert (await b2.wait_phase("results"))["result"] == final["result"]
            assert_frames_blind(a, b2)

    doc = next(iter(store.docs.values()))
    assert doc["status"] == "completed"
    assert sum(v["voter_type"] == "ai" for v in doc["votes"]) == 2  # AI voted in both rounds
    # every request to Claude used the intended settings
    assert claude.requests
    for request, body in claude.requests:
        assert request.headers["anthropic-version"] == llm.API_VERSION
        assert body["thinking"] == {"type": "disabled"} and "temperature" not in body


async def test_one_human_two_ai_end_to_end(live_server):
    port, store, _ = await live_server("one_human_two_ai", discussion_seconds=1.0)
    async with Tab(port) as solo:
        await solo.wait_phase("voting", 1)
        await solo.send(type="vote", target=solo.state["you"])
        await solo.wait_phase("discussion", 2)
        await solo.send(type="chat", text="i still think it should be me")
        final = await solo.wait_phase("results")
        assert final["result"]["decision_maker"] in final["players"]
        errors = [f for f in solo.frames if f["type"] == "error"]
        assert errors == []
        assert_frames_blind(solo)
    doc = next(iter(store.docs.values()))
    assert doc["composition"] == {"humans": 1, "ai": 2}
    assert sum(v["voter_type"] == "ai" for v in doc["votes"]) == 4


async def test_health_endpoint_reveals_nothing(live_server):
    port, _, _ = await live_server("one_human_two_ai")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://127.0.0.1:{port}/api/health")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
