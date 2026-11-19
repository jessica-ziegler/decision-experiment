# AI Usage Log

## Tools and models

| Tool / agent | Model | Used for |
|---|---|---|
| Claude (Anthropic), agent mode in the Claude app: a cloud Linux workspace with file editing, shell and web search | Claude Opus 5.5 (`claude-opus-5-5`) | Clarifying questions, architecture, all code, Docker setup, README, testing |

The **runtime** AI participants in the app call Claude Haiku 5.5 (`claude-haiku-5-5`) by
default (configurable in `config.yml`). That model is part of the product, not of the
development process.

## Prompts (in order)

### 1. Kick-off
> I need to implement an MVP for the task attached. Ask me any questions you might have around the implementation.

*(The attachment didn't come through, and Claude asked for it again.)*

### 2. Attached the project spec
> [project spec attached]

*(Claude replied with the defaults it planned to use: server-side timers over WebSockets,
one URL with each tab as a participant, shuffled player letters, no participant counts in
the waiting room, conditions in `config.yml` switched by an env var, a prompt log in this
file. It then asked four multiple-choice questions.)*

### 3. Answers to Claude's clarifying questions

| Claude's question | My answer |
|---|---|
| How should the AI participants generate their chat messages and votes? (LLM + scripted fallback / LLM only / scripted only) | **LLM only** |
| Which database? (MongoDB / PostgreSQL) | **MongoDB** |
| How should between-round feedback and the final Decision Maker be decided? (Show round-1 tally, round 2 decides / hidden until end / sum of both rounds) | **Show round-1 tally, round 2 decides** |
| Where should the finished code go? (zip / push to my GitHub repo) | **Zip for me to push** |

*(From here Claude built the first version on its own: backend, frontend, Docker, README. It tested
the backend with scripted WebSocket clients for all three conditions, using an in-memory
MongoDB stand-in and a fake LLM, and tested the UI with a headless browser driving two tabs.)*

### 4. Provider
> I need it to work with claude.

*(Claude checked the current Claude API docs. Haiku 5.5 has adaptive thinking on by default,
and thinking tokens count against `max_tokens`. With the tiny token limits the first version
used (5 tokens for a vote), agents would likely have gone silent. Claude made the agents
Claude-only and removed the OpenAI path. It now disables thinking, sets `effort: low`,
raises the token limits, moves to API version `2026-10-21` (which removes `temperature`),
and treats a response with no text as an error, including in the startup check. It added
unit tests against a mocked Claude API, plus a full session run against a fake Claude
server over HTTP.)*

### 5. Waiting time
> How long does a participant have to wait for others?

*(Claude explained: no upper limit. A participant waits until all human seats are filled,
plus a random 5–12 s hold counted from the first person's arrival. Claude suggested a timeout
and advised against filling empty seats with AI, because that changes the condition.)*

### 6. Max wait with AI backfill
> Add: After max. 30 seconds, the other two seats are filled with AI.

*(Claude added `experiment.max_wait_seconds: 30`. Once 30 s have passed since the first human
joined, any still-empty human seats become Claude agents and the session starts. Each session
records the configured condition plus the actual `composition`, `backfilled_ai_seats`, and a
`backfill` flag per participant. Because any condition can now need Claude, the backend asks
for the API key in every condition unless `max_wait_seconds` is null. Claude also made sure a
latecomer can't join a session that is already starting. Tested: a full group isn't
backfilled, 1 of 2 humans gets 1 AI, 2 of 3 humans gets 1 AI.)*

### 7. Overview
> What happens in this mvp?

*(Claude walked through a session from a participant's point of view and what is stored.)*

### 8. Data
> where can i find the database?

*(Claude explained where the data lives: the `mongo` service, a Docker volume, the
`group_decision_chat` database and its `sessions` collection. It showed how to query it with
`mongosh`, export it with `mongoexport`, and publish the port for a GUI.)*

### 9. AI personalities
> Okay, great. Now I want to add different AI personalities. Let's define 10 varying system prompts, from which the software can choose before starting the experiment. The personalities should act very differently in the chat.

*(Claude wrote `personalities.yml` with 10 characters: leader, facilitator, shy, skeptic,
cheerleader, analyst, joker, follower, strategist, pragmatist. Each one specifies writing
style, discussion behaviour and voting rule, plus pacing knobs: messages per round, typing
speed, opening delay. Each AI seat draws a distinct personality at random when the session
starts, and the pool can be restricted or a seat pinned in `config.yml`. The session record
stores each AI's personality id and prompt. The agent prompt was split into a shared base,
holding the task and the never-reveal rules, plus the personality. Tests were added for
loading, validation and selection.)*

### 10. Architecture diagram
> Give me a UML class diagram of the architecture for my presentation slide.

*(Claude generated a 16:9 UML class diagram as SVG and PNG. It covers the frontend hook,
components and state type; the backend classes Session, SessionManager, Agent, Participant,
Config, Personality, ClaudeClient, Store and Phase, plus the voting and personalities
utilities; and MongoDB and the Claude API as external services. Each element is labelled
with its relationships and multiplicities.)*

### 11. Tests
> Okay, awesome. As a final step, I need some unittests for checking the functionality. Can you add some? I saw that you have already run your code on tests, maybe you can reuse them.

*(Claude turned its scratch end-to-end scripts into a pytest suite of 63 tests that runs in
about 30 s with no MongoDB, API key or Docker. The suite covers the session engine, AI
agents, end-to-end WebSocket sessions against the real app, voting, personalities, config,
the Claude client and the database layer. To make this possible, agent timings moved into a
swappable `Pacing` object, and a `pytest.ini` was added because plain `pytest` couldn't
import the app. Writing the tests uncovered a bug: agent tasks were left running when a
session was cancelled mid-round. Claude fixed it.)*

### 12. Windows test failure
> E       UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d in position 4184: character maps to <undefined>

*(Claude traced it to Windows reading files as cp1252 by default. `personalities.yml` is UTF-8
and contains emojis (byte 0x8d is part of 👍), and the config loader opened it without an
encoding. Claude set `encoding="utf-8"` on every file read and write in the app and tests and
reproduced the exact error under cp1252. It verified with Python's `EncodingWarning` that no
code path in the test run still relies on the platform default, and added the PowerShell
syntax for switching conditions to the README.)*

### 13. Diagram again
> Okay, now I need the architecture diagram again.

*(Claude re-sent the UML class diagram and noted that it still matched the code.)*

### 14. Diagram with tests
> Include the test classes, if any.

*(Claude pointed out that the 63 tests are pytest functions, not classes, and added the test
doubles and drivers to the diagram as a "Tests" area: FakeStore, FakeLLM, FakeWS, Human,
helpers, conftest fixtures, Tab, FakeClaudeAPI, RecordingCollection, and the test modules.
Each fake is marked with the real class it replaces. Claude also added the new `Pacing` class
to the backend and kept the original diagram as a separate file.)*

<!-- Append any further prompts below, in the same format. -->
