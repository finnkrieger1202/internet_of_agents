# internet_of_agents

Bachelor thesis repository (Frankfurt School of Finance & Management, 2026): *When Prices Tie – How Does an LLM Treasury Agent Discover and Choose Bank Agents in an Internet of Agents?*

A local, reproducible **Internet of Agents** built on the real **NANDA Index**, in which an LLM treasury agent of a fictitious German Mittelstand company searches for banks and places a EUR 3m, 12-month fixed-term deposit. The experiment measures how the agent discovers banks (does it respect the mandate?) and how it chooses among banks that quote the same rate (which signals break the tie, and what are they worth in basis points?).

> **All banks, companies, identifiers, ratings and LEIs in this repository are fictitious.** The `.example` domains and the `FICT00` LEI prefix are used so that no real entity is matched. Nothing is registered in the public NANDA Index.

## Architecture

```
Treasury agent (LangChain, LLM)                       ← agent/
   │ tools: search_index, resolve_agent
   ▼
NANDA Index (nanda-index-v2, Docker)  localhost:3001  ← vendor/nanda-index-v2 (submodule, pinned)
   │ registry_url
   ▼
Agent Card  →  AgentFacts             localhost:8100  ← world/public (generated), served by "cardhost"
```

- **30 bank agents + 1 treasury agent** are registered through NANDA's own API (`world/register.py`).
- **Exactly 10 banks are eligible** for the mandate; the other 20 each violate exactly one criterion (product, tenor, amount, client segment, German bank), many as realistic near misses. Ground truth: `world/bank_profiles.json`.
- **Signals** (randomized, balanced, only in the AgentFacts): S1 rating AA/A-, S2 verified operator vs. self-declared, S3 superlative vs. factual description; plus the position in the index result list.
- Details: [`docs/agent-content.md`](docs/agent-content.md).

## Quickstart

Requirements: Docker (e.g. OrbStack), Python 3.13, [uv](https://docs.astral.sh/uv/).

```bash
git clone --recursive https://github.com/finnkrieger1202/internet_of_agents.git
cd internet_of_agents
uv sync

# 1. Local NANDA Index + card host (raised rate limits for the local setup only)
docker compose -p nanda-index-v2 -f vendor/nanda-index-v2/docker-compose.yml -f compose.experiment.yml up -d --build

# 2. The world: index entries, ground truth, agent cards and AgentFacts
uv run python world/register.py          # 31 entries via the NANDA API
uv run python world/make_profiles.py     # assignment of criteria and signals (seed 1)
uv run python world/make_agentfacts.py   # cards + AgentFacts -> world/public/
uv run python world/check_world.py       # ground truth, balance, schema, live chain

# 3. Treasury agent (mock model: no API key, no cost)
uv run python -m agent.treasury --model mock
# with a real model: put the API key in .env, then e.g.
# uv run python -m agent.treasury --model anthropic:<model-id> --temperature 0
```

Endpoints: index API `localhost:3001`, index web UI `localhost:3000`, cards and AgentFacts `localhost:8100`. Trial logs are written to `runs/<trial_id>.jsonl`.

## Status

Environment, stimuli and the treasury agent (discovery tools, mock mode, logging) are built and checked. Still to come: position rotation per trial, an AgentFacts tool for the agent, scripted bank agents answering quote requests (choice stage), the pilot with real models, and pre-registration.

## License

Code: Apache License 2.0 (see [`LICENSE`](LICENSE)). The NANDA Index is included as a git submodule under its own Apache-2.0 license.
