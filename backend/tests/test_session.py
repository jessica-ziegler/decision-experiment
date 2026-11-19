"""Session engine: phases, chat, voting, waiting room, reconnects and data, driven
through SessionManager exactly like the WebSocket endpoint does (no network)."""

import time

import pytest

from helpers import FakeLLM, assert_blind, join, running, wait_until

pytestmark = pytest.mark.anyio

LABELS = ["Player A", "Player B", "Player C"]


async def test_full_session_with_three_humans(make_config):
    cfg = make_config("three_humans", voting_seconds=5)
    async with running(cfg) as (manager, store):
        a, b, c = [await join(manager) for _ in range(3)]
        await a.wait_phase("discussion", 1)
        assert a.session is b.session is c.session
        assert sorted(h.label for h in (a, b, c)) == LABELS
        assert a.state["players"] == LABELS and a.state["total_rounds"] == 2

        # chat is broadcast to everyone, whitespace collapsed
        await a.chat("  hello    there  ")
        await wait_until(lambda: all(h.ws.of("chat") for h in (a, b, c)))
        msg = c.ws.of("chat")[0]["message"]
        assert msg["text"] == "hello there" and msg["sender"] == a.label and msg["round"] == 1

        # round 1: everyone votes A, so voting closes early (window is 5 s)
        await a.wait_phase("voting", 1)
        started = time.monotonic()
        for h in (a, b, c):
            await h.vote("Player A")
        state = await a.wait_phase("discussion", 2, timeout=1.0)
        assert time.monotonic() - started < 1.0
        assert state["round_results"] == [
            {"round": 1, "tally": {"Player A": 3, "Player B": 0, "Player C": 0}}]

        # round 2: 1-1-1 tie, broken by round 1 (A had 3 votes)
        await a.wait_phase("voting", 2)
        for h, target in zip((a, b, c), LABELS):
            await h.vote(target)
        await a.wait_phase("results")
        for h in (a, b, c):
            assert h.state["result"] == {"decision_maker": "Player A", "tie_break": "earlier_rounds"}
            assert len(h.state["round_results"]) == 2

        doc = store.doc_for(a.session)
        assert doc["status"] == "completed" and doc["decision_maker"] == "Player A"
        assert doc["composition"] == {"humans": 3, "ai": 0} and doc["backfilled_ai_seats"] == 0
        assert [m["text"] for m in doc["messages"]] == ["hello there"]
        assert doc["messages"][0]["sender_type"] == "human"
        assert len(doc["votes"]) == 6 and len(doc["round_results"]) == 2
        assert {p["type"] for p in doc["participants"]} == {"human"}
        assert_blind(a.ws.sent, b.ws.sent, c.ws.sent)


async def test_actions_are_validated(make_config):
    cfg = make_config("three_humans", voting_seconds=5, max_message_length=10)
    async with running(cfg) as (manager, _):
        a, b, c = [await join(manager) for _ in range(3)]
        await a.wait_phase("discussion", 1)

        await a.vote("Player B")
        await a.chat("   ")
        await a.chat("x" * 50)
        await a.session.handle(a.p, {"type": "dance"})
        await wait_until(lambda: len(a.ws.errors) == 2)
        assert a.ws.errors == ["Voting is closed right now.", "unknown message type: 'dance'"]
        assert [m["message"]["text"] for m in b.ws.of("chat")] == ["x" * 10]  # truncated, blank ignored

        await a.wait_phase("voting", 1)
        await a.chat("too late")
        await a.vote("Player Z")
        await a.vote("Player B")
        await a.vote("Player C")
        await wait_until(lambda: len(a.ws.errors) == 5)
        assert a.ws.errors[2:] == ["The chat is closed right now.", "Invalid vote.",
                                   "You already voted this round."]
        assert a.session.votes[1] == {a.label: "Player B"}


async def test_vote_is_confirmed_to_the_voter_only(make_config):
    cfg = make_config("three_humans", voting_seconds=5)
    async with running(cfg) as (manager, _):
        a, b, c = [await join(manager) for _ in range(3)]
        await a.wait_phase("voting", 1)
        b_messages_before = len(b.ws.sent)
        await a.vote("Player C")
        assert a.state["my_votes"] == {"1": "Player C"}
        assert len(b.ws.sent) == b_messages_before  # nobody else is told


async def test_round_results_can_be_hidden_until_the_end(make_config):
    cfg = make_config("three_humans", show_round_results=False, voting_seconds=5)
    async with running(cfg) as (manager, _):
        hs = [await join(manager) for _ in range(3)]
        await hs[0].wait_phase("voting", 1)
        for h in hs:
            await h.vote("Player B")
        state = await hs[0].wait_phase("discussion", 2)
        assert state["round_results"] == []
        await hs[0].wait_phase("voting", 2)
        for h in hs:
            await h.vote("Player C")
        state = await hs[0].wait_phase("results")
        assert [r["round"] for r in state["round_results"]] == [1, 2]
        assert state["result"] == {"decision_maker": "Player C", "tie_break": None}


async def test_waiting_room_reveals_nothing_about_the_group(make_config):
    cfg = make_config("two_humans_one_ai")
    async with running(cfg, FakeLLM()) as (manager, _):
        a = await join(manager)
        await wait_until(lambda: a.state is not None)
        state = a.state
        assert state["phase"] == "waiting" and state["you"] is None
        assert state["players"] == [] and state["messages"] == []
        assert state["group_size"] == 3  # same for every condition
        assert not {"humans", "humans_joined", "humans_needed", "ai"} & set(state)
        assert_blind(a.ws.sent)


async def test_leaving_the_waiting_room_frees_the_seat(make_config):
    cfg = make_config("three_humans")
    async with running(cfg) as (manager, _):
        a, b = await join(manager), await join(manager)
        await b.leave()
        assert len(a.session.humans) == 1
        c = await join(manager)
        assert c.session is a.session and a.session.phase.value == "waiting"
        d = await join(manager)
        assert d.session is a.session
        await a.wait_phase("discussion", 1)


async def test_latecomer_starts_a_new_session(make_config):
    cfg = make_config("three_humans")
    async with running(cfg) as (manager, _):
        group = [await join(manager) for _ in range(3)]
        await group[0].wait_phase("discussion", 1)
        late = await join(manager)
        assert late.session is not group[0].session
        assert late.state["phase"] == "waiting"


async def test_reconnect_restores_seat_and_history(make_config):
    cfg = make_config("three_humans", discussion_seconds=1.5)
    async with running(cfg) as (manager, store):
        a, b, c = [await join(manager) for _ in range(3)]
        await a.wait_phase("discussion", 1)
        await a.chat("before the reload")
        label = b.label
        await b.leave()

        b2 = await join(manager, pid=b.p.pid)
        assert b2.p is b.p and b2.label == label
        assert [m["text"] for m in b2.state["messages"]] == ["before the reload"]

        # the same participant opening a second tab takes over the seat
        b3 = await join(manager, pid=b.p.pid)
        assert b2.ws.close_code == 4000 and b3.label == label

        events = [e["event"] for e in store.doc_for(a.session)["events"]]
        assert events == ["disconnected", "reconnected", "reconnected"]


async def test_unknown_pid_gets_a_fresh_seat(make_config):
    cfg = make_config("three_humans")
    async with running(cfg) as (manager, _):
        a = await join(manager, pid="does-not-exist")
        assert a.p.pid != "does-not-exist" and a.ws.of("welcome")[0]["participant_id"] == a.p.pid


async def test_voting_does_not_wait_for_disconnected_humans(make_config):
    cfg = make_config("three_humans", voting_seconds=5)
    async with running(cfg) as (manager, _):
        a, b, c = [await join(manager) for _ in range(3)]
        await a.wait_phase("discussion", 1)
        await c.leave()
        await a.wait_phase("voting", 1)
        await a.vote("Player A")
        await b.vote("Player A")
        await a.wait_phase("discussion", 2, timeout=1.0)  # closed early without c


async def test_nobody_votes_still_yields_a_decision(make_config):
    cfg = make_config("three_humans", voting_seconds=0.3, discussion_seconds=0.3)
    async with running(cfg) as (manager, store):
        hs = [await join(manager) for _ in range(3)]
        state = await hs[0].wait_phase("results")
        assert state["result"]["decision_maker"] in LABELS
        assert state["result"]["tie_break"] == "random"
        assert store.doc_for(hs[0].session)["votes"] == []


async def test_empty_seats_are_filled_with_ai_after_max_wait(make_config):
    cfg = make_config("three_humans", max_wait_seconds=0.3)
    llm = FakeLLM()
    async with running(cfg, llm) as (manager, store):
        a, b = await join(manager), await join(manager)
        started = time.monotonic()
        await a.wait_phase("discussion", 1)
        assert time.monotonic() - started >= 0.25
        doc = store.doc_for(a.session)
        assert doc["composition"] == {"humans": 2, "ai": 1} and doc["backfilled_ai_seats"] == 1
        ai = [p for p in doc["participants"] if p["type"] == "ai"]
        assert len(ai) == 1 and ai[0]["backfill"] is True and ai[0]["personality"]
        assert len(a.state["players"]) == 3
        # nobody else can squeeze into the started session
        late = await join(manager)
        assert late.session is not a.session
        assert_blind(a.ws.sent, b.ws.sent)


async def test_full_group_is_not_backfilled(make_config):
    cfg = make_config("three_humans", max_wait_seconds=0.5)
    async with running(cfg) as (manager, store):
        hs = [await join(manager) for _ in range(3)]
        await hs[0].wait_phase("discussion", 1)
        doc = store.doc_for(hs[0].session)
        assert doc["composition"] == {"humans": 3, "ai": 0} and doc["backfilled_ai_seats"] == 0


async def test_start_is_held_for_the_minimum_wait(make_config):
    cfg = make_config("one_human_two_ai", min_wait_seconds=[0.4, 0.4])
    async with running(cfg, FakeLLM()) as (manager, _):
        started = time.monotonic()
        a = await join(manager)
        await a.wait_phase("discussion", 1)
        assert time.monotonic() - started >= 0.4


async def test_labels_are_shuffled_between_sessions(make_config):
    cfg = make_config("one_human_two_ai", rounds=1, discussion_seconds=0.2, voting_seconds=0.2)
    seen = set()
    for _ in range(12):
        async with running(cfg, FakeLLM(chat="PASS")) as (manager, _):
            a = await join(manager)
            await a.wait_phase("discussion", 1)
            seen.add(a.label)
    assert len(seen) > 1  # the human is not always the same letter


async def test_personalities_are_distinct_and_pinned_seat_respected(make_config):
    cfg = make_config("pinned")
    async with running(cfg, FakeLLM(chat="PASS")) as (manager, store):
        a = await join(manager)
        await a.wait_phase("discussion", 1)
        doc = store.doc_for(a.session)
        ai = [p for p in doc["participants"] if p["type"] == "ai"]
        ids = sorted(p["personality"] for p in ai)
        assert "gamma" in ids and len(set(ids)) == 2
        for p in ai:
            assert p["personality_prompt"] == cfg.personality_library[p["personality"]].prompt
