from pathlib import Path

import pytest
import yaml

from app import agents
from app.config import load_config

# Near-instant agents so whole sessions run in about a second.
FAST_PACING = agents.Pacing(end_margin=0.2, read_delay=(0, 0), idle=(0.1, 0.2),
                            min_typing=0, max_typing=0.02, vote_delay=(0, 0.05), vote_margin=0)

TEST_PERSONALITIES = {
    name: {
        "name": name.title(),
        "prompt": f"You are {name.title()}. {desc}",
        "opening_delay": [0, 0.05],
        "typing_speed": [1000, 1000],
        "max_messages_per_round": 2,
    }
    for name, desc in [
        ("alpha", "You are bold and always vote for yourself."),
        ("beta", "You are quiet and agree with the majority."),
        ("gamma", "You are skeptical and ask a lot of questions."),
    ]
}

CONDITIONS = {
    "three_humans": ["human", "human", "human"],
    "two_humans_one_ai": ["human", "human", "ai"],
    "one_human_two_ai": ["human", "ai", "ai"],
    "pinned": ["human", {"type": "ai", "personality": "gamma"}, "ai"],
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fast_agents(monkeypatch):
    monkeypatch.setattr(agents, "PACING", FAST_PACING)


@pytest.fixture
def write_config(tmp_path, monkeypatch):
    """Writes config.yml + personalities.yml with short timings; returns the path."""
    monkeypatch.delenv("CONDITION", raising=False)

    def _write(condition: str = "three_humans", ai: dict | None = None, **experiment) -> Path:
        exp = dict(rounds=2, discussion_seconds=0.6, voting_seconds=0.6,
                   show_round_results=True, min_wait_seconds=[0, 0],
                   max_wait_seconds=None, max_message_length=40)
        exp.update(experiment)
        cfg = {"condition": condition, "conditions": CONDITIONS, "experiment": exp,
               "ai": {"model": "test-model", **(ai or {})}}
        (tmp_path / "personalities.yml").write_text(yaml.safe_dump(TEST_PERSONALITIES), encoding="utf-8")
        path = tmp_path / "config.yml"
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def make_config(write_config):
    def _make(condition: str = "three_humans", ai: dict | None = None, **experiment):
        return load_config(write_config(condition, ai, **experiment))

    return _make
