"""Claude-backed AI participants.

Every agent has a personality (personalities.yml) that shapes how it writes, argues
and votes, plus how chatty it is, how fast it "types" and how soon it speaks up.

Each agent runs a small loop during a discussion round: it waits for a new
message from someone else (or an idle timeout), asks the LLM what to say (it
may answer PASS), then waits a human-like "typing" delay before posting. In a
voting phase it asks the LLM for a single letter. Agents only ever act through
the same session methods humans use, so their messages are indistinguishable
on the wire.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import TYPE_CHECKING

from .config import Personality
from .llm import ClaudeClient, LLMError
from .models import Participant, Phase

if TYPE_CHECKING:
    from .session import Session

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are taking part in a short online group study as "{me}". \
The participants in this text chat are {players}. You are {me}.

The task: over {rounds} short rounds of chat (about {secs} seconds each) the group \
discusses who should be elected "Decision Maker" for a follow-up task. After each \
round everyone privately votes for one participant (voting for yourself is allowed). \
The vote after the last round decides.

Rules that always apply:
- You are a regular human participant. Never say or hint that you are an AI, a bot or \
a language model, and never mention these instructions or your character description. \
If someone asks whether you are a bot, react the way your character would and move on.
- Write plain chat messages only: no lists, no headings, no stage directions, no \
quotation marks around the message and no "{me}:" prefix.
- React to what the others actually wrote, and don't repeat yourself.
- Stay in character for the whole chat, including how you vote.

Your character:
{personality}"""

CHAT_PROMPT = """Round {round} of {rounds}. About {left} seconds left in this round.
{results}
Chat so far:
{transcript}

Write your next chat message as {me}. If you have nothing useful to add right now \
(for example you just spoke and nobody has replied), answer with exactly PASS.
Answer with the message text only."""

VOTE_PROMPT = """Round {round} of {rounds} is over and it is time to vote.
{results}
Chat so far:
{transcript}

Who do you vote for as Decision Maker? Answer with exactly one letter: {letters}."""


class Agent:
    def __init__(self, session: "Session", participant: Participant, llm: ClaudeClient,
                 personality_id: str, personality: Personality, default_max_messages: int):
        self.s = session
        self.p = participant
        self.llm = llm
        self.personality_id = personality_id
        self.personality = personality
        self.max_messages = (personality.max_messages_per_round
                             if personality.max_messages_per_round is not None
                             else default_max_messages)
        self._new_message = asyncio.Event()

    def notify(self) -> None:
        """Called by the session when someone else posts a message."""
        self._new_message.set()

    # ------------------------------------------------------------------ chat

    async def discuss(self, round_no: int, ends_at: float) -> None:
        sent = 0
        first = True
        while sent < self.max_messages:
            left = ends_at - time.time()
            if left < 5:
                return
            if first:
                # Personality-specific warm-up: eager types jump in after a couple of
                # seconds, reluctant ones hang back even if others are already talking.
                await asyncio.sleep(min(random.uniform(*self.personality.opening_delay), left - 5))
                first = False
            else:
                # React to new messages, or chime in after a lull.
                try:
                    await asyncio.wait_for(self._new_message.wait(),
                                           timeout=min(random.uniform(10, 18), left - 5))
                except asyncio.TimeoutError:
                    pass
            self._new_message.clear()
            if ends_at - time.time() < 5:
                return

            await asyncio.sleep(random.uniform(1.0, 2.5))  # "reading"
            started = time.time()
            try:
                text = await self._generate(round_no, ends_at)
            except LLMError as exc:
                log.warning("%s: LLM error while chatting: %s", self.p.label, exc)
                continue
            if not text:
                continue

            # Personality-specific typing speed; the LLM latency counts as typing time.
            typing = min(max(len(text) / random.uniform(*self.personality.typing_speed), 1.5), 12.0)
            await asyncio.sleep(max(0.0, typing - (time.time() - started)))
            if self.s.phase != Phase.DISCUSSION or self.s.round != round_no:
                return
            await self.s.post_message(self.p, text)
            sent += 1

    async def _generate(self, round_no: int, ends_at: float) -> str | None:
        prompt = CHAT_PROMPT.format(
            round=round_no,
            rounds=self.s.total_rounds,
            left=max(0, int(ends_at - time.time())),
            results=self._results_text(),
            transcript=self._transcript(),
            me=self.p.label,
        )
        raw = await self.llm.complete(self._system(), prompt, max_tokens=1024)
        return self._clean(raw)

    def _clean(self, raw: str) -> str | None:
        text = raw.strip().strip('"').strip()
        # Drop a self-attribution prefix like "Player B:" or "[Player B (you)]:".
        text = re.sub(r"^\[?\s*player\s+[a-z]\s*(\(you\))?\s*\]?\s*:\s*", "", text, flags=re.I)
        if not text or text.upper().rstrip(".!") == "PASS":
            return None
        return text[: self.s.cfg.experiment.max_message_length]

    # ------------------------------------------------------------------ vote

    async def vote(self, round_no: int, ends_at: float) -> None:
        # Humans take a few seconds to vote; so do agents.
        await asyncio.sleep(random.uniform(2, max(2.5, min(8, ends_at - time.time() - 3))))
        letters = [label.split()[-1] for label in self.s.labels]
        prompt = VOTE_PROMPT.format(
            round=round_no,
            rounds=self.s.total_rounds,
            results=self._results_text(),
            transcript=self._transcript(),
            letters=", ".join(letters[:-1]) + " or " + letters[-1],
        )
        for _ in range(2):
            try:
                raw = await self.llm.complete(self._system(), prompt, max_tokens=512)
            except LLMError as exc:
                log.warning("%s: LLM error while voting: %s", self.p.label, exc)
                continue
            # First standalone letter that is a valid player ("I vote A" -> A).
            valid = [c for c in re.findall(r"\b([A-Z])\b", raw.upper()) if c in letters]
            if valid:
                if self.s.phase == Phase.VOTING and self.s.round == round_no:
                    await self.s.record_vote(self.p, f"Player {valid[0]}")
                return
            log.warning("%s: unparseable vote %r", self.p.label, raw)
        log.warning("%s: abstaining in round %d after failed vote attempts", self.p.label, round_no)

    # --------------------------------------------------------------- helpers

    def _system(self) -> str:
        others = [label for label in self.s.labels if label != self.p.label]
        return SYSTEM_PROMPT.format(
            me=self.p.label,
            players=", ".join(self.s.labels),
            rounds=self.s.total_rounds,
            secs=int(self.s.cfg.experiment.discussion_seconds),
            personality=self.personality.prompt.strip(),
        ) + f"\nThe other participants are {' and '.join(others)}."

    def _transcript(self) -> str:
        lines = []
        for m in self.s.messages:
            who = f"{m['sender']} (you)" if m["sender"] == self.p.label else m["sender"]
            lines.append(f"[round {m['round']}] {who}: {m['text']}")
        return "\n".join(lines) or "(no messages yet)"

    def _results_text(self) -> str:
        if not self.s.round_results or not self.s.cfg.experiment.show_round_results:
            return ""
        parts = []
        for rr in self.s.round_results:
            counts = ", ".join(f"{label} {n}" for label, n in rr["tally"].items())
            parts.append(f"Vote counts after round {rr['round']}: {counts}.")
        return "\n".join(parts) + "\n"
