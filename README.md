# Group Decision Chat

A side project for running small real-time group decision experiments with humans and AI.
Three participants (any mix of humans and Claude agents, and nobody knows who is who) chat
for 2 rounds of about a minute each, vote after each round, and elect a **Decision Maker**.

**Stack:** React (Vite, TypeScript) · FastAPI (WebSockets) · MongoDB · Docker Compose

## Run it

Requires Docker with Compose v2.

```bash
cp .env.example .env          # add ANTHROPIC_API_KEY
docker compose up --build
```

The AI participants are Claude (`claude-haiku-5-5` by default) via the Claude API. The key
comes from the [Claude Console](https://platform.claude.com), and API usage is billed
separately from a Claude Pro/Max subscription. The key is needed in every condition,
because empty human seats are filled with AI after 30 s of waiting (see below). To run
3 humans without a key, set `max_wait_seconds: null` in `config.yml`.

Open **http://localhost:8080** once per human participant. Each browser tab is its own
participant, so you can test every condition on one machine with tabs side by side.
Reloading a tab keeps your seat.

## Switch conditions

All three conditions are defined in [`config.yml`](config.yml). Pick one with an env var:

| Condition | Command |
|---|---|
| 3 humans | `CONDITION=three_humans docker compose up --build` |
| 2 humans + 1 AI | `CONDITION=two_humans_one_ai docker compose up --build` (default) |
| 1 human + 2 AI | `CONDITION=one_human_two_ai docker compose up --build` |

You can also set `CONDITION=` in `.env`, or edit `condition:` in `config.yml` and run
`docker compose restart backend`. The same file holds round count, durations, voting
window, waiting-room hold and maximum wait, the Claude model / effort / thinking settings, and
which AI personalities are used (the personalities themselves are in
[`personalities.yml`](personalities.yml), see below). The backend validates both files at startup and stops with a clear error if
it's invalid. It does the same if AI participants are configured without a working API key
or model: it makes one test call to Claude before accepting participants.

## How a session runs

```
waiting room ──(all human seats filled + 5–12 s hold, or after 30 s: empty seats → AI)──►
   round 1 chat (60s) ► vote (≤20s) ► round 2 chat, with the round-1 tally shown ► vote
   ► final results shown to everyone
```

```
Browser ──WebSocket──► nginx ──► FastAPI
                                  ├─ SessionManager   routes tabs to the session that is filling
                                  ├─ Session          asyncio state machine, server-side timers
                                  │   └─ Agent ×n     Claude-backed participants ──► Claude API
                                  └─ Store ─────────► MongoDB (one document per session)
```

## Design decisions and trade-offs

**The server owns the state.** Each session is a single asyncio task stepping through
`waiting → discussion → voting → … → results`. All timers run on the server. Clients only
render snapshots (`remaining_ms` included), so tabs can't drift apart, and a client that
reconnects gets the full state back.

**Keeping the condition blind** was the main design constraint:
- `Player A/B/C` letters are shuffled every session, so the AI isn't always "Player C".
- AI messages and votes go through the same code path and wire format as human ones. Clients
  never receive participant types, and `/api/health` deliberately exposes nothing about the
  condition.
- The waiting room shows **no participant counts**, since "waiting for 1 more human" would
  reveal the group's composition. The start is also held for a random 5–12 s after the first
  human joins. Otherwise the 1-human condition would start instantly and give itself away.
- Agents pause to "read", type at a human-like speed set by their personality (LLM latency
  counts toward that), send only a few messages per round, and can answer `PASS` to stay
  quiet. There are no typing indicators for anyone.

**Between rounds**, the anonymous vote tally from round 1 is shown during round 2. It gives
the second discussion something to react to without revealing who voted for whom.

**Decision rule:** the round-2 vote decides. A tie goes to whichever tied candidate got
more round-1 votes, and if they're still tied, to a random pick among them. The method used
(`tie_break`) is stored and shown to participants. Self-votes are allowed, there is one
vote per round (final once cast), and anyone who doesn't vote abstains. The vote closes
early once every connected participant has voted.

**AI agents are Claude only**, with no scripted fallback, so the AI conditions are
believable. Each agent's system prompt is a shared base (the task, plus rules such as stay in
character and never reveal being an AI) followed by its **personality**. On each turn the
agent sees the transcript, the time left and the earlier tallies. Votes are a separate call
that expects a single letter. If a call fails, it is retried once (on 429/5xx/overloaded).
After that the agent stays silent for that turn, or abstains from the vote, and the error is
logged.

**Personalities.** [`personalities.yml`](personalities.yml) defines 10 characters that
behave very differently in the chat:

| id | Character | Chat behaviour | Votes for |
|---|---|---|---|
| `leader` | Confident self-nominator | puts themself forward right away, short punchy sentences | themself |
| `facilitator` | Organizer | proposes a process, asks quiet people directly, summarises | the clearest volunteer / round-1 leader |
| `shy` | Reluctant one | lowercase, 1–6 words, mostly silent, speaks up late | whoever sounds most confident |
| `skeptic` | Skeptic | questions everyone's reasons, pushes back on quick consensus | the best-argued case, not the loudest |
| `cheerleader` | Enthusiast | exclamation marks and emojis, hypes others up | the most popular person |
| `analyst` | Analyst | formal full sentences, proposes criteria and weighs them | the best fit to the criteria |
| `joker` | Joker | jokes and light sarcasm, the occasional real point | the most likeable, or ironically themself |
| `follower` | Follower | "yeah agree with B", switches to the majority | the current favourite |
| `strategist` | Competitive negotiator | lobbies for allies, picks at rivals' arguments | themself |
| `pragmatist` | Impatient pragmatist | terse, wants to settle it fast and vote | whoever volunteered first |

Besides the prompt, each personality sets how many messages it sends per round, its typing
speed and how long it waits before first speaking (2–5 s for the leader, 12–25 s for the shy
one). When a session starts, every AI seat draws a personality at random, and two AIs in the
same group get different ones (unless the pool is smaller than the number of AI seats). `ai.personalities` in `config.yml` restricts the pool (e.g.
`[skeptic, shy]`), and a seat can be pinned in a condition, e.g.
`one_human_two_ai: [human, {type: ai, personality: skeptic}, ai]`. To add your own, add an
entry to `personalities.yml`.

The default model is Claude Haiku 5.5, the fastest model, because replies have to arrive within
the human-like typing delay. It runs at `effort: low` with thinking disabled: Haiku 5.5 thinks
by default, and thinking would add latency and eat into `max_tokens`. Claude is called with
plain `httpx` on the Messages API (version `2026-10-21`) rather than the SDK, to keep the
backend's dependencies small.

**Data:** MongoDB holds one document per session, with the configured `condition` and the
`composition` actually run, the config snapshot, participants (label, true type,
`personality` id and the exact prompt it ran with, `backfill` flag), every message and vote (with sender type and timestamps), the
round tallies, connect/disconnect events and the result. Sessions are written once they
start; abandoned waiting rooms aren't stored. To inspect:

```bash
docker compose exec mongo mongosh group_decision_chat --eval 'db.sessions.find().sort({started_at:-1}).limit(1)'
```

**Waiting room:** one session fills at a time, first come first served. Leaving before the
start frees the seat. If human seats are still empty **30 s** after the first person joined
(`experiment.max_wait_seconds`), they are filled with Claude agents and the session starts.
Participants see nothing different. So nobody waits longer than 30 s, but a session's actual
composition can differ from the configured condition (e.g. a "3 humans" session with only two
people becomes 2 humans + 1 AI). Each session document records this as `composition` and
`backfilled_ai_seats`, and each participant has a `backfill` flag, so these sessions can be
analysed separately or excluded. Once a session starts, a dropped participant keeps their seat and can
reconnect (a reload is enough). If they don't come back, they just don't vote.

### Known limitations / not built yet
- Live session state is in memory in a single backend process. Scaling out would need sticky
  sessions or Redis pub/sub, and a backend restart drops sessions that are in progress.
- There's no participant authentication or recruitment-platform ID (e.g. a Prolific PID URL
  parameter), no consent/debrief pages, and no admin dashboard or CSV export.
- A human who drops out after the start isn't replaced, and an AI doesn't take over their seat.
- Tests are limited to unit tests (voting rules, config and personality selection, Claude
  request/response handling against a mocked HTTP API), plus a scripted end-to-end run of all three conditions used during
  development.

## Local development (without Docker)

```bash
# backend (needs a local MongoDB on :27017)
cd backend && pip install -r requirements.txt
CONFIG_PATH=../config.yml uvicorn app.main:app --reload
# frontend (proxies /ws and /api to :8000)
cd frontend && npm install && npm run dev        # http://localhost:5173

# tests
cd backend && pip install pytest && pytest
```

## Repository layout

```
config.yml            experiment parameters and the 3 conditions
personalities.yml     the 10 AI personalities (prompt + pacing)
docker-compose.yml    mongo + backend + frontend (nginx)
backend/app/          main.py (FastAPI/WebSocket) · session.py (state machine, manager)
                      agents.py (AI participants) · personalities.py · llm.py (Claude client)
                      voting.py · db.py · config.py
frontend/src/         App.tsx · useExperiment.ts (WebSocket hook) · components/
ai_prompts.md         AI usage log: prompts, models and tools used
```
