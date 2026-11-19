"""AI agents: what they post, how they vote, how they fail, and what Claude is told."""

from types import SimpleNamespace

import pytest

from app.agents import Agent
from app.llm import LLMError
from app.models import Participant
from helpers import FakeLLM, assert_blind, join, running

pytestmark = pytest.mark.anyio


def ai_messages(doc):
    return [m for m in doc["messages"] if m["sender_type"] == "ai"]


def ai_votes(doc):
    return [v for v in doc["votes"] if v["voter_type"] == "ai"]


async def test_agents_chat_and_vote_like_participants(make_config):
    cfg = make_config("one_human_two_ai", discussion_seconds=1.0)
    llm = FakeLLM(chat="i could do it", vote="B")
    async with running(cfg, llm) as (manager, store):
        human = await join(manager)
        await human.wait_phase("results", timeout=10)
        doc = store.doc_for(human.session)

        msgs = ai_messages(doc)
        assert msgs and {m["text"] for m in msgs} == {"i could do it"}
        # personality cap: at most 2 messages per agent per round
        for label in {m["sender"] for m in msgs}:
            for r in (1, 2):
                assert sum(m["sender"] == label and m["round"] == r for m in msgs) <= 2
        # both agents vote in both rounds, for the letter Claude answered
        assert len(ai_votes(doc)) == 4
        assert {v["target"] for v in ai_votes(doc)} == {"Player B"}
        # the human sees AI messages as ordinary chat
        seen = [m["message"]["sender"] for m in human.ws.of("chat")]
        assert set(seen) == {m["sender"] for m in msgs}
        assert_blind(human.ws.sent)


async def test_pass_keeps_agents_silent(make_config):
    cfg = make_config("one_human_two_ai", rounds=1)
    llm = FakeLLM(chat="PASS")
    async with running(cfg, llm) as (manager, store):
        human = await join(manager)
        await human.wait_phase("results", timeout=10)
        assert llm.prompts("chat")  # they were asked...
        assert ai_messages(store.doc_for(human.session)) == []  # ...and stayed quiet


async def test_llm_errors_do_not_break_the_session(make_config):
    cfg = make_config("one_human_two_ai", voting_seconds=0.4)
    llm = FakeLLM(chat=LLMError("overloaded"), vote=LLMError("overloaded"))
    async with running(cfg, llm) as (manager, store):
        human = await join(manager)
        await human.wait_phase("voting", 2, timeout=10)
        await human.vote(human.label)
        state = await human.wait_phase("results", timeout=10)
        doc = store.doc_for(human.session)
        assert ai_messages(doc) == [] and ai_votes(doc) == []  # silent, abstained
        assert state["result"]["decision_maker"] == human.label  # the only vote decides
        assert doc["status"] == "completed"


@pytest.mark.parametrize("reply,expected", [
    ("A", "Player A"), ("Player C", "Player C"), ("I vote b.", "Player B"),
    ("I'd go with C", "Player C"),
])
async def test_vote_replies_are_parsed(make_config, reply, expected):
    cfg = make_config("one_human_two_ai", rounds=1, discussion_seconds=0.3)
    async with running(cfg, FakeLLM(chat="PASS", vote=reply)) as (manager, store):
        human = await join(manager)
        await human.wait_phase("results", timeout=10)
        assert {v["target"] for v in ai_votes(store.doc_for(human.session))} == {expected}


async def test_unparseable_vote_is_retried_once_then_abstains(make_config):
    cfg = make_config("one_human_two_ai", rounds=1, discussion_seconds=0.3)
    llm = FakeLLM(chat="PASS", vote="no idea, sorry")
    async with running(cfg, llm) as (manager, store):
        human = await join(manager)
        await human.wait_phase("results", timeout=10)
        assert ai_votes(store.doc_for(human.session)) == []
        assert len(llm.prompts("vote")) == 4  # 2 agents x 2 attempts


async def test_prompts_carry_personality_transcript_and_tally(make_config):
    cfg = make_config("pinned", discussion_seconds=1.0)
    llm = FakeLLM(chat="hey", vote="A")
    async with running(cfg, llm) as (manager, _):
        human = await join(manager)
        await human.wait_phase("discussion", 1)
        await human.chat("who wants it?")
        await human.wait_phase("results", timeout=10)

        session = human.session
        gamma = next(a for a in session.agents if a.personality_id == "gamma")
        gamma_calls = [c for c in llm.calls if f'as "{gamma.p.label}"' in c["system"]]
        assert gamma_calls
        system = gamma_calls[0]["system"]
        assert cfg.personality_library["gamma"].prompt.strip() in system
        assert "Never say or hint that you are an AI" in system
        others = [lab for lab in session.labels if lab != gamma.p.label]
        assert f"The other participants are {others[0]} and {others[1]}." in system

        chat_prompts = [c["prompt"] for c in gamma_calls if c["kind"] == "chat"]
        assert any(f"{human.label}: who wants it?" in p for p in chat_prompts)
        assert any(f"{gamma.p.label} (you): hey" in p for p in chat_prompts)
        round2 = [p for p in chat_prompts if p.startswith("Round 2 of 2")]
        assert round2 and all("Vote counts after round 1" in p for p in round2)


def make_agent(max_len=40):
    session = SimpleNamespace(cfg=SimpleNamespace(experiment=SimpleNamespace(max_message_length=max_len)))
    personality = SimpleNamespace(max_messages_per_round=None, prompt="x")
    return Agent(session, Participant(kind="ai", label="Player B"), None, "x", personality, 3)


@pytest.mark.parametrize("raw,expected", [
    ("hey all", "hey all"),
    ('"hey all"', "hey all"),
    ("Player B: hey all", "hey all"),
    ("[Player B (you)]: hey all", "hey all"),
    ("PASS", None), ("pass.", None), ("   ", None),
    ("x" * 100, "x" * 40),
])
def test_agent_output_is_cleaned(raw, expected):
    assert make_agent()._clean(raw) == expected


def test_max_messages_falls_back_to_config_default():
    agent = make_agent()
    assert agent.max_messages == 3
