import random

from app.voting import decide, tally

LABELS = ["Player A", "Player B", "Player C"]


def test_tally_counts_every_label():
    assert tally({"Player A": "Player B", "Player C": "Player B"}, LABELS) == {
        "Player A": 0, "Player B": 2, "Player C": 0,
    }


def test_final_round_majority_wins():
    tallies = {1: {"Player A": 3, "Player B": 0, "Player C": 0},
               2: {"Player A": 0, "Player B": 2, "Player C": 1}}
    assert decide(tallies, 2) == ("Player B", None)


def test_tie_broken_by_earlier_round():
    tallies = {1: {"Player A": 0, "Player B": 1, "Player C": 2},
               2: {"Player A": 1, "Player B": 1, "Player C": 1}}
    assert decide(tallies, 2) == ("Player C", "earlier_rounds")


def test_earlier_round_only_considers_tied_candidates():
    # A led round 1, but only B and C are tied in round 2.
    tallies = {1: {"Player A": 2, "Player B": 1, "Player C": 0},
               2: {"Player A": 0, "Player B": 1, "Player C": 1}}
    assert decide(tallies, 2) == ("Player B", "earlier_rounds")


def test_full_tie_is_random_but_valid():
    tallies = {1: {"Player A": 1, "Player B": 1, "Player C": 1},
               2: {"Player A": 1, "Player B": 1, "Player C": 1}}
    winner, how = decide(tallies, 2, random.Random(0))
    assert winner in LABELS and how == "random"


def test_no_votes_at_all_still_produces_a_winner():
    zero = {label: 0 for label in LABELS}
    winner, how = decide({1: dict(zero), 2: dict(zero)}, 2, random.Random(1))
    assert winner in LABELS and how == "random"
