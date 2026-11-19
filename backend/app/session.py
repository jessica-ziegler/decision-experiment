"""Server-authoritative experiment sessions.

A Session is a small state machine driven by one asyncio task:
    waiting -> (discussion r -> voting r) x rounds -> results
All timers live on the server; clients only render the snapshots they get.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import WebSocket

from . import voting
from .agents import DEFAULT_PERSONAS, Agent
from .config import Config
from .db import Store
from .llm import ClaudeClient
from .models import Participant, Phase

log = logging.getLogger(__name__)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


class Session:
    def __init__(self, cfg: Config, store: Store, llm: ClaudeClient | None,
                 on_done: Callable[["Session"], None] | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.cfg = cfg
        self.store = store
        self.llm = llm
        self.on_done = on_done

        self.phase = Phase.WAITING
        self.round = 0
        self.total_rounds = cfg.experiment.rounds
        self.phase_ends_at: float | None = None
        self.phase_duration: float | None = None

        self.humans: list[Participant] = []
        self.human_slots = cfg.n_humans  # shrinks if empty seats are filled with AI
        self.ais = [Participant(kind="ai", persona=p.persona)
                    for p in cfg.participants if p.type == "ai"]
        self.backfilled_seats = 0
        self.participants: list[Participant] = []  # all, sorted by label once started
        self.labels: list[str] = []
        self.agents: list[Agent] = []

        self.messages: list[dict[str, Any]] = []
        self.votes: dict[int, dict[str, str]] = {}
        self.round_results: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None

        self._first_join_at: float | None = None
        self._closed = False  # no more joins once the start sequence begins
        self._all_voted = asyncio.Event()
        self._msg_seq = 0

    # ------------------------------------------------------------ joining

    @property
    def is_full(self) -> bool:
        return len(self.humans) >= self.human_slots

    @property
    def accepting(self) -> bool:
        return self.phase == Phase.WAITING and not self._closed and not self.is_full

    def add_human(self, ws: WebSocket) -> Participant:
        assert self.accepting
        p = Participant(kind="human", ws=ws)
        self.humans.append(p)
        if self._first_join_at is None:
            self._first_join_at = time.time()
        log.info("[%s] human joined waiting room (%d/%d)", self.id, len(self.humans), self.human_slots)
        return p

    def remove_human(self, p: Participant) -> None:
        """Only used before the session starts (slot is freed for someone else)."""
        if p in self.humans:
            self.humans.remove(p)
            log.info("[%s] human left waiting room (%d/%d)", self.id, len(self.humans), self.human_slots)
        if not self.humans:
            self._first_join_at = None

    def get(self, pid: str) -> Participant | None:
        return next((p for p in self.humans if p.pid == pid), None)

    # ------------------------------------------------------------ main loop

    async def run(self) -> None:
        try:
            await self._wait_for_participants()
            await self._start()
            for r in range(1, self.total_rounds + 1):
                await self._discussion(r)
                await self._voting(r)
            await self._finish()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("[%s] session crashed", self.id)
        finally:
            if self.on_done:
                self.on_done(self)

    async def _wait_for_participants(self) -> None:
        target_wait = random.uniform(*self.cfg.experiment.min_wait_seconds)
        max_wait = self.cfg.experiment.max_wait_seconds
        while True:
            if self._first_join_at is not None:
                waited = time.time() - self._first_join_at
                if self.is_full and waited >= target_wait:
                    break
                if max_wait is not None and waited >= max_wait:
                    self._fill_empty_seats_with_ai()
                    break
            await asyncio.sleep(0.25)
        self._closed = True

    def _fill_empty_seats_with_ai(self) -> None:
        missing = self.human_slots - len(self.humans)
        if missing <= 0:
            return
        self.ais += [Participant(kind="ai", backfill=True) for _ in range(missing)]
        self.human_slots = len(self.humans)
        self.backfilled_seats = missing
        log.info("[%s] max wait reached: filling %d empty seat(s) with AI", self.id, missing)

    async def _start(self) -> None:
        everyone = self.humans + self.ais
        random.shuffle(everyone)  # random letter assignment per session
        for i, p in enumerate(everyone):
            p.label = f"Player {chr(ord('A') + i)}"
        self.participants = everyone
        self.labels = [p.label for p in everyone]

        personas = random.sample(DEFAULT_PERSONAS, k=len(DEFAULT_PERSONAS))
        for i, p in enumerate(a for a in everyone if a.kind == "ai"):
            persona = p.persona or personas[i % len(personas)]
            p.persona = persona
            assert self.llm is not None, "AI participants require an LLM client"
            self.agents.append(Agent(self, p, self.llm, persona, self.cfg.ai.max_messages_per_round))

        log.info("[%s] starting: %s", self.id, ", ".join(
            f"{p.label}={p.kind}{' (backfill)' if p.backfill else ''}" for p in everyone))
        await self.store.create_session({
            "_id": self.id,
            "status": "running",
            "condition": self.cfg.condition,  # as configured
            # as actually run (differs when empty seats were filled with AI)
            "composition": {"humans": len(self.humans), "ai": len(self.ais)},
            "backfilled_ai_seats": self.backfilled_seats,
            "config": {
                "experiment": self.cfg.experiment.model_dump(),
                "ai": self.cfg.ai.model_dump(),
            },
            "created_at": datetime.fromtimestamp(self._first_join_at or time.time(), timezone.utc),
            "started_at": _now_dt(),
            "participants": [
                {
                    "pid": p.pid,
                    "label": p.label,
                    "type": p.kind,
                    "persona": p.persona if p.kind == "ai" else None,
                    "backfill": p.backfill,
                    "joined_at": datetime.fromtimestamp(p.joined_at, timezone.utc) if p.kind == "human" else None,
                }
                for p in everyone
            ],
            "messages": [],
            "votes": [],
            "round_results": [],
            "events": [],
        })

    async def _discussion(self, r: int) -> None:
        self.round = r
        self._set_phase(Phase.DISCUSSION, self.cfg.experiment.discussion_seconds)
        await self.broadcast_state()
        tasks = [asyncio.create_task(a.discuss(r, self.phase_ends_at)) for a in self.agents]
        await asyncio.sleep(self.cfg.experiment.discussion_seconds)
        await self._cancel(tasks)

    async def _voting(self, r: int) -> None:
        self.votes[r] = {}
        self._all_voted.clear()
        self._set_phase(Phase.VOTING, self.cfg.experiment.voting_seconds)
        await self.broadcast_state()
        tasks = [asyncio.create_task(a.vote(r, self.phase_ends_at)) for a in self.agents]
        try:
            await asyncio.wait_for(self._all_voted.wait(), timeout=self.cfg.experiment.voting_seconds)
        except asyncio.TimeoutError:
            pass
        await self._cancel(tasks)

        result = {"round": r, "tally": voting.tally(self.votes[r], self.labels)}
        self.round_results.append(result)
        await self.store.push(self.id, "round_results", result)

    async def _finish(self) -> None:
        tallies = {rr["round"]: rr["tally"] for rr in self.round_results}
        winner, tie_break = voting.decide(tallies, self.total_rounds)
        self.result = {"decision_maker": winner, "tie_break": tie_break}
        self._set_phase(Phase.RESULTS, None)
        log.info("[%s] finished: decision maker %s (tie-break: %s)", self.id, winner, tie_break)
        await self.store.set(self.id, {
            "status": "completed",
            "ended_at": _now_dt(),
            "decision_maker": winner,
            "tie_break": tie_break,
        })
        await self.broadcast_state()

    def _set_phase(self, phase: Phase, duration: float | None) -> None:
        self.phase = phase
        self.phase_duration = duration
        self.phase_ends_at = time.time() + duration if duration else None

    @staticmethod
    async def _cancel(tasks: list[asyncio.Task]) -> None:
        for t in tasks:
            t.cancel()
        for t, res in zip(tasks, await asyncio.gather(*tasks, return_exceptions=True)):
            if isinstance(res, Exception) and not isinstance(res, asyncio.CancelledError):
                log.error("agent task failed: %r", res)

    # ------------------------------------------------------------ actions

    async def handle(self, p: Participant, data: dict[str, Any]) -> None:
        kind = data.get("type")
        if kind == "chat":
            error = await self.post_message(p, str(data.get("text", "")))
        elif kind == "vote":
            error = await self.record_vote(p, str(data.get("target", "")))
        else:
            error = f"unknown message type: {kind!r}"
        if error:
            await self._send(p, {"type": "error", "message": error})

    async def post_message(self, p: Participant, text: str) -> str | None:
        if self.phase != Phase.DISCUSSION:
            return "The chat is closed right now."
        text = " ".join(text.split())[: self.cfg.experiment.max_message_length]
        if not text:
            return None
        self._msg_seq += 1
        msg = {"id": self._msg_seq, "round": self.round, "sender": p.label,
               "text": text, "ts": time.time()}
        self.messages.append(msg)
        await self.broadcast({"type": "chat", "message": msg})
        for agent in self.agents:
            if agent.p is not p:
                agent.notify()
        await self.store.push(self.id, "messages", {
            **msg, "ts": datetime.fromtimestamp(msg["ts"], timezone.utc), "sender_type": p.kind,
        })
        return None

    async def record_vote(self, p: Participant, target: str) -> str | None:
        if self.phase != Phase.VOTING:
            return "Voting is closed right now."
        if target not in self.labels:
            return "Invalid vote."
        round_votes = self.votes[self.round]
        if p.label in round_votes:
            return "You already voted this round."
        round_votes[p.label] = target
        await self.store.push(self.id, "votes", {
            "round": self.round, "voter": p.label, "voter_type": p.kind,
            "target": target, "ts": _now_dt(),
        })
        if p.kind == "human":
            await self.send_state(p)  # confirms the vote to the voter only
        expected = [x for x in self.participants if x.kind == "ai" or x.ws is not None]
        if all(x.label in round_votes for x in expected):
            self._all_voted.set()
        return None

    async def log_event(self, p: Participant, event: str) -> None:
        if self.phase != Phase.WAITING:
            await self.store.push(self.id, "events", {"pid": p.pid, "label": p.label,
                                                      "event": event, "ts": _now_dt()})

    # ------------------------------------------------------------ outbound

    def snapshot(self, p: Participant) -> dict[str, Any]:
        started = self.phase != Phase.WAITING
        show_results = self.cfg.experiment.show_round_results or self.phase == Phase.RESULTS
        return {
            "type": "state",
            "phase": self.phase.value,
            "round": self.round,
            "total_rounds": self.total_rounds,
            "remaining_ms": (max(0, int((self.phase_ends_at - time.time()) * 1000))
                             if self.phase_ends_at else None),
            "phase_duration_ms": int(self.phase_duration * 1000) if self.phase_duration else None,
            "you": p.label,
            "players": self.labels if started else [],
            "messages": self.messages if started else [],
            "my_votes": {str(r): v[p.label] for r, v in self.votes.items() if p.label in v},
            "round_results": self.round_results if show_results else [],
            "result": self.result,
            "max_message_length": self.cfg.experiment.max_message_length,
            "group_size": len(self.cfg.participants),
            "discussion_seconds": self.cfg.experiment.discussion_seconds,
        }

    async def send_state(self, p: Participant) -> None:
        await self._send(p, self.snapshot(p))

    async def broadcast_state(self) -> None:
        await asyncio.gather(*(self.send_state(p) for p in self.humans))

    async def broadcast(self, payload: dict[str, Any]) -> None:
        await asyncio.gather(*(self._send(p, payload) for p in self.humans))

    @staticmethod
    async def _send(p: Participant, payload: dict[str, Any]) -> None:
        ws = p.ws
        if ws is None:
            return
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001  (client went away mid-send)
            pass


class SessionManager:
    """Routes connections to sessions. One session fills up at a time."""

    def __init__(self, cfg: Config, store: Store, llm: ClaudeClient | None):
        self.cfg = cfg
        self.store = store
        self.llm = llm
        self.sessions: dict[str, Session] = {}
        self._by_pid: dict[str, Session] = {}
        self._waiting: Session | None = None
        self._tasks: set[asyncio.Task] = set()

    async def connect(self, ws: WebSocket, pid: str | None) -> tuple[Session, Participant]:
        # Reconnect (page reload, network blip) -> same seat, full state snapshot.
        if pid and (session := self._by_pid.get(pid)) and (p := session.get(pid)):
            old = p.ws
            p.ws = ws
            if old is not None and old is not ws:
                try:
                    await old.close(code=4000)
                except Exception:  # noqa: BLE001
                    pass
            await session.log_event(p, "reconnected")
            return session, p

        if self._waiting is None or not self._waiting.accepting:
            self._waiting = Session(self.cfg, self.store, self.llm, on_done=self._session_done)
            self.sessions[self._waiting.id] = self._waiting
            task = asyncio.create_task(self._waiting.run())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        session = self._waiting
        p = session.add_human(ws)
        self._by_pid[p.pid] = session
        return session, p

    async def disconnect(self, session: Session, p: Participant, ws: WebSocket) -> None:
        if p.ws is not ws:  # already replaced by a newer connection
            return
        p.ws = None
        if session.phase == Phase.WAITING:
            session.remove_human(p)
            self._by_pid.pop(p.pid, None)
        else:
            await session.log_event(p, "disconnected")

    def _session_done(self, session: Session) -> None:
        if self._waiting is session:
            self._waiting = None
        # Keep finished sessions around for a while so reloads still show results.
        asyncio.get_running_loop().call_later(15 * 60, self._forget, session)

    def _forget(self, session: Session) -> None:
        self.sessions.pop(session.id, None)
        for p in session.humans:
            self._by_pid.pop(p.pid, None)

    async def shutdown(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
