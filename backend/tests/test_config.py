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
