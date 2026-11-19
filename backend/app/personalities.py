"""Assigning personalities to AI seats at session start."""

from __future__ import annotations

import random


def choose(pinned: list[str | None], pool: list[str], rng: random.Random | None = None) -> list[str]:
    """Return one personality id per AI seat.

    `pinned[i]` is a fixed id for seat i (from config.yml) or None. Unpinned seats
    draw at random from `pool`, avoiding ids already used in this session as long
    as there are enough left, so two AIs in one group behave differently.
    """
    rng = rng or random.Random()
    used = {p for p in pinned if p}
    available = [p for p in pool if p not in used]
    rng.shuffle(available)
    result = []
    for fixed in pinned:
        if fixed:
            result.append(fixed)
        elif available:
            result.append(available.pop())
        else:  # more AI seats than distinct personalities: allow repeats
            result.append(rng.choice(pool))
    return result
