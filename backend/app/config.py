"""Loads and validates config.yml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ParticipantSpec(BaseModel):
    type: Literal["human", "ai"]
    persona: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, value):
        # Allow `[human, ai]` shorthand in YAML.
        return {"type": value} if isinstance(value, str) else value


class ExperimentSettings(BaseModel):
    rounds: int = Field(2, ge=1, le=10)
    discussion_seconds: float = Field(60, gt=0)
    voting_seconds: float = Field(20, gt=0)
    show_round_results: bool = True
    min_wait_seconds: tuple[float, float] = (5.0, 12.0)
    # After this long (since the first human joined) any human seats still
    # empty are filled with AI agents and the session starts. None = wait forever.
    max_wait_seconds: float | None = Field(30.0, gt=0)
    max_message_length: int = Field(300, ge=10, le=2000)


class AISettings(BaseModel):
    model: str = "claude-haiku-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    thinking: Literal["disabled", "adaptive"] = "disabled"
    max_messages_per_round: int = Field(3, ge=0)

    @model_validator(mode="after")
    def _check_thinking(self) -> "AISettings":
        if self.thinking == "disabled" and self.effort in ("xhigh", "max"):
            raise ValueError("ai.thinking: disabled only works with effort high or below")
        return self


class Config(BaseModel):
    condition: str
    conditions: dict[str, list[ParticipantSpec]]
    experiment: ExperimentSettings = ExperimentSettings()
    ai: AISettings = AISettings()

    @model_validator(mode="after")
    def _validate(self) -> "Config":
        if self.condition not in self.conditions:
            raise ValueError(
                f"condition '{self.condition}' is not defined; "
                f"available: {', '.join(self.conditions)}"
            )
        for name, people in self.conditions.items():
            if not 2 <= len(people) <= 26:
                raise ValueError(f"condition '{name}' must have 2-26 participants")
            if not any(p.type == "human" for p in people):
                raise ValueError(f"condition '{name}' needs at least one human")
        lo, hi = self.experiment.min_wait_seconds
        if lo < 0 or lo > hi:
            raise ValueError("experiment.min_wait_seconds must be [min, max] with 0 <= min <= max")
        return self

    @property
    def participants(self) -> list[ParticipantSpec]:
        return self.conditions[self.condition]

    @property
    def n_humans(self) -> int:
        return sum(p.type == "human" for p in self.participants)

    @property
    def n_ai(self) -> int:
        return sum(p.type == "ai" for p in self.participants)

    @property
    def may_need_ai(self) -> bool:
        """AI is configured, or empty human seats may be filled with AI."""
        return self.n_ai > 0 or (self.experiment.max_wait_seconds is not None and self.n_humans > 1)


def load_config(path: str | os.PathLike | None = None) -> Config:
    path = Path(path or os.getenv("CONFIG_PATH", "config.yml"))
    raw = yaml.safe_load(path.read_text()) or {}
    # CONDITION env var overrides the file so conditions can be switched
    # from the command line without editing anything.
    if override := os.getenv("CONDITION", "").strip():
        raw["condition"] = override
    return Config.model_validate(raw)
