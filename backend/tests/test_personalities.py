import random

from app.personalities import choose

POOL = ["leader", "shy", "skeptic", "joker"]


def test_unpinned_seats_get_distinct_personalities():
    for seed in range(50):
        picks = choose([None, None, None], POOL, random.Random(seed))
        assert len(set(picks)) == 3 and set(picks) <= set(POOL)


def test_pinned_seat_is_kept_and_not_reused():
    for seed in range(50):
        picks = choose(["shy", None, None], POOL, random.Random(seed))
        assert picks[0] == "shy" and "shy" not in picks[1:] and len(set(picks)) == 3


def test_more_seats_than_pool_allows_repeats():
    picks = choose([None, None, None], ["skeptic"], random.Random(0))
    assert picks == ["skeptic"] * 3


def test_draw_is_random_across_sessions():
    seen = {tuple(choose([None, None], POOL, random.Random(s))) for s in range(40)}
    assert len(seen) > 5
