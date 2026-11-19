from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from . import db, llm
from .config import load_config
from .session import SessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # no log line per Claude request
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    log.info("Condition '%s': %d human(s), %d AI agent(s); %d rounds x %ss discussion + %ss voting",
             cfg.condition, cfg.n_humans, cfg.n_ai, cfg.experiment.rounds,
             cfg.experiment.discussion_seconds, cfg.experiment.voting_seconds)
    if cfg.experiment.max_wait_seconds is not None and cfg.n_humans > 1:
        log.info("Empty human seats are filled with AI after %ss of waiting",
                 cfg.experiment.max_wait_seconds)

    store = db.Store(os.getenv("MONGO_URL", "mongodb://localhost:27017"),
                     os.getenv("MONGO_DB", "group_decision_chat"))
    await store.connect()

    llm_client = None
    if cfg.may_need_ai:
        llm_client = llm.client_from_env(cfg.ai)
        await llm_client.check()
        log.info("Claude ready: %s (effort=%s, thinking=%s)", cfg.ai.model, cfg.ai.effort, cfg.ai.thinking)

    app.state.manager = SessionManager(cfg, store, llm_client)
    try:
        yield
    finally:
        await app.state.manager.shutdown()
        if llm_client:
            await llm_client.aclose()
        await store.close()


app = FastAPI(title="Multi-participant Human-AI Experiment", lifespan=lifespan)


@app.get("/api/health")
async def health():
    # Deliberately exposes nothing about the condition: participants could
    # otherwise infer how many of the others are AI.
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, pid: str | None = None):
    await ws.accept()
    manager: SessionManager = ws.app.state.manager
    session, p = await manager.connect(ws, pid)
    await ws.send_json({"type": "welcome", "participant_id": p.pid})
    await session.send_state(p)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                await session.handle(p, data)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(session, p, ws)
