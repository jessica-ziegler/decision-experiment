"""Loads and validates config.yml (and the personality library it points to)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


def _check_range(value: tuple[float, float], name: str) -> None:
    lo, hi = value
    if lo < 0 or lo > hi:
        raise ValueError(f"{name} must be [min, max] with 0 <= min <= max")


class ParticipantSpec(BaseModel):
    type: Literal["human", "ai"]
    personality: str | None = None  # pin an AI seat to a personality id

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, value):
        # Allow `[human, ai]` shorthand in YAML.
        return {"type": value} if isinstance(value, str) else value


class Personality(BaseModel):
    name: str
    prompt: str = Field(min_length=20)
    max_messages_per_round: int | None = Field(None, ge=0)
    typing_speed: tuple[float, float] = (4.0, 7.0)  # characters per second
    opening_delay: tuple[float, float] = (3.0, 9.0)  # seconds before first considering a message

    @model_validator(mode="after")
    def _ranges(self) -> "Personality":
        _check_range(self.opening_delay, "opening_delay")
        _check_range(self.typing_speed, "typing_speed")
        if self.typing_speed[0] <= 0:
            raise ValueError("typing_speed must be > 0")
        return self


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
    max_messages_per_round: int = Field(3, ge=0)  # default if a personality sets none
    personalities_file: str = "personalities.yml"
    # Pool that AI seats draw from at session start: "all" or a list of ids.
    personalities: Literal["all"] | list[str] = "all"

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
    personality_library: dict[str, Personality] = {}  # loaded from ai.personalities_file

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
        _check_range(self.experiment.min_wait_seconds, "experiment.min_wait_seconds")

        if self.may_need_ai and not self.personality_library:
            raise ValueError(f"AI participants need personalities, but none were found in "
                             f"{self.ai.personalities_file}")
        known = set(self.personality_library)
        pool = [] if self.ai.personalities == "all" else self.ai.personalities
        pinned = [p.personality for ps in self.conditions.values() for p in ps if p.personality]
        if unknown := sorted(set(pool + pinned) - known):
            raise ValueError(f"unknown personality id(s): {', '.join(unknown)}; "
                             f"available: {', '.join(known)}")
        if self.ai.personalities != "all" and not pool:
            raise ValueError("ai.personalities must be 'all' or a non-empty list of ids")
        return self

    @property
    def participants(self) -> list[ParticipantSpec]:
        return self.conditions[self.condition]

    @property
    def personality_pool(self) -> list[str]:
        if self.ai.personalities == "all":
            return list(self.personality_library)
        return list(self.ai.personalities)

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
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # CONDITION env var overrides the file so conditions can be switched
    # from the command line without editing anything.
    if override := os.getenv("CONDITION", "").strip():
        raw["condition"] = override

    # The personality library lives in its own file, resolved relative to config.yml.
    lib_name = (raw.get("ai") or {}).get("personalities_file", "personalities.yml")
    lib_path = Path(lib_name) if Path(lib_name).is_absolute() else path.parent / lib_name
    raw["personality_library"] = (yaml.safe_load(lib_path.read_text(encoding="utf-8")) or {}) if lib_path.exists() else {}
    return Config.model_validate(raw)
