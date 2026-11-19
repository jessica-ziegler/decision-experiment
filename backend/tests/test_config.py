from pathlib import Path

import pytest

from app.config import load_config

ROOT_CONFIG = Path(__file__).resolve().parents[2] / "config.yml"


@pytest.mark.parametrize("condition,humans,ai", [
    ("three_humans", 3, 0), ("two_humans_one_ai", 2, 1), ("one_human_two_ai", 1, 2),
])
def test_repo_config_conditions(monkeypatch, condition, humans, ai):
    monkeypatch.setenv("CONDITION", condition)
    cfg = load_config(ROOT_CONFIG)
    assert (cfg.n_humans, cfg.n_ai) == (humans, ai)
    assert cfg.experiment.max_wait_seconds == 30
    # every shipped condition may need Claude: configured AI, or backfill of empty seats
    assert cfg.may_need_ai


def test_no_backfill_and_no_ai_needs_no_claude(tmp_path):
    f = tmp_path / "c.yml"
    f.write_text("condition: h\nconditions: {h: [human, human]}\nexperiment: {max_wait_seconds: null}\n")
    assert not load_config(f).may_need_ai


def test_unknown_condition_is_rejected(monkeypatch):
    monkeypatch.setenv("CONDITION", "nope")
    with pytest.raises(ValueError, match="not defined"):
        load_config(ROOT_CONFIG)


def test_shipped_personalities_load_and_differ(monkeypatch):
    monkeypatch.delenv("CONDITION", raising=False)
    cfg = load_config(ROOT_CONFIG)
    lib = cfg.personality_library
    assert len(lib) == 10
    assert len({p.prompt for p in lib.values()}) == 10
    assert len({p.name for p in lib.values()}) == 10
    assert cfg.personality_pool == list(lib)


def _write(tmp_path, body):
    (tmp_path / "personalities.yml").write_text(
        "calm: {name: Calm, prompt: 'You are calm and write short polite messages.'}\n"
        "loud: {name: Loud, prompt: 'You are loud and write in capital letters a lot.'}\n")
    f = tmp_path / "config.yml"
    f.write_text(body)
    return f


def test_pinned_and_pooled_personalities_are_validated(tmp_path):
    ok = _write(tmp_path, "condition: c\nconditions: {c: [human, {type: ai, personality: loud}]}\n"
                          "ai: {personalities: [calm]}\n")
    cfg = load_config(ok)
    assert cfg.participants[1].personality == "loud" and cfg.personality_pool == ["calm"]

    bad = _write(tmp_path, "condition: c\nconditions: {c: [human, {type: ai, personality: nope}]}\n")
    with pytest.raises(ValueError, match="unknown personality"):
        load_config(bad)


def test_ai_without_personality_file_is_rejected(tmp_path):
    f = tmp_path / "c.yml"
    f.write_text("condition: c\nconditions: {c: [human, ai]}\n")
    with pytest.raises(ValueError, match="need personalities"):
        load_config(f)
