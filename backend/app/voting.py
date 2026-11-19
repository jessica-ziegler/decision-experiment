"""Vote counting and Decision Maker selection (pure functions, unit-tested)."""

from __future__ import annotations

import random


def tally(votes: dict[str, str], labels: list[str]) -> dict[str, int]:
    """votes maps voter label -> target label. Every label gets a count (0 if none)."""
    counts = {label: 0 for label in labels}
    for target in votes.values():
        if target in counts:
            counts[target] += 1
    return counts


def decide(
    tallies: dict[int, dict[str, int]],
    final_round: int,
    rng: random.Random | None = None,
) -> tuple[str, str | None]:
    """Pick the Decision Maker.

    The final round's vote decides. Ties are broken by the earlier rounds'
    tallies (most recent first), and if still tied, uniformly at random.

    Returns (winner_label, tie_break) where tie_break is None,
    "earlier_rounds" or "random".
    """
    rng = rng or random.Random()
    final = tallies[final_round]
    top = max(final.values())
    tied = [label for label, n in final.items() if n == top]
    if len(tied) == 1:
        return tied[0], None

    for r in range(final_round - 1, 0, -1):
        earlier = tallies.get(r, {})
        best = max(earlier.get(label, 0) for label in tied)
        tied = [label for label in tied if earlier.get(label, 0) == best]
        if len(tied) == 1:
            return tied[0], "earlier_rounds"

    return rng.choice(sorted(tied)), "random"
