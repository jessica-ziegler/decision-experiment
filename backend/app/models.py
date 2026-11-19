from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Phase(str, Enum):
    WAITING = "waiting"
    DISCUSSION = "discussion"
    VOTING = "voting"
    RESULTS = "results"


@dataclass
class Participant:
    kind: str  # "human" | "ai" -- never sent to clients (blind condition)
    pid: str = field(default_factory=lambda: uuid.uuid4().hex)
    label: str | None = None  # "Player A" etc., assigned when the session starts
    personality: str | None = None  # AI only: personality id
    backfill: bool = False  # AI that took an empty human seat after max wait
    ws: Any = None  # WebSocket for connected humans
    joined_at: float = field(default_factory=time.time)
