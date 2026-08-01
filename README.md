# Clickathon 2026 — Automated Root-Cause Analyst

Jalagaara Gang's entry for InMobi's Click-a-thon 2026. A system that detects when an ad metric moves, **drills down in ClickHouse** to name the segment responsible, and produces a plain-language diagnosis where **every number is real and computed** — including what it ruled out.

> **ClickHouse is the detective. The LLM is the journalist.**

## Start here
1. [`AGENTS.md`](AGENTS.md) — architecture, stack, non-negotiables. **Read first.**
2. [`docs/PLAN.md`](docs/PLAN.md) — milestones, the algorithm, 24h timeline.
3. [`docs/TASKS.md`](docs/TASKS.md) — the task board.
4. [`docs/CODING_STANDARDS.md`](docs/CODING_STANDARDS.md) — how we write code.
5. [`contracts/evidence_bundle.schema.json`](contracts/evidence_bundle.schema.json) — **the contract** everything flows through.

## Working with your agent
Each person owns a lane; point your AI agent at its prompt plus `AGENTS.md`:
- Lane A — Data & ClickHouse → [`prompts/01-data-clickhouse.md`](prompts/01-data-clickhouse.md)
- Lane B — Detection & RCA → [`prompts/02-detection-rca.md`](prompts/02-detection-rca.md)
- Lane C — Narrator & Orchestration → [`prompts/03-narrator-orchestration.md`](prompts/03-narrator-orchestration.md)
- Lane D — Dashboard → [`prompts/04-dashboard.md`](prompts/04-dashboard.md)

## Setup
Copy [`.env.example`](.env.example) → `.env` and fill in ClickHouse, Langfuse, and LLM creds. Never commit `.env`.

The problem statement and synthetic dataset live in [`InMobi/`](InMobi/) (read-only).
