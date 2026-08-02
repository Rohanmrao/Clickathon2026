# Automated Root-Cause Analyst

**Team:** Jalagaara Gang · **Track:** InMobi — *From alert to answer*

> A metric moved. It tells you **which segment** did it, in seconds, with numbers you can
> recompute yourself.

**ClickHouse is the detective. The LLM is the journalist.** Every figure in a diagnosis is
computed by SQL before the model ever sees it, and a guardrail rejects any number in the prose
that is not in the evidence.

| | |
|---|---|
| **Live demo** | **https://clickathon.kangasys.com** |
| **Langfuse traces** | https://traces.kangasys.com |
| **LibreChat** | https://chat.kangasys.com |
| **Demo video** | _to be added_ |
| **Pitch deck** | `pitch-deck.pdf` — _to be added_ |

## Team

| Name | GitHub |
|---|---|
| Rohan M Rao | [@Rohanmrao](https://github.com/Rohanmrao) |
| Ankith Dinakar | [@Ankith2502](https://github.com/Ankith2502) |
| Shashank | [@ShashankEC37](https://github.com/ShashankEC37) |
| Shreyas Bharadhwaj S P | _handle to be added_ |

## What it does

Ask *"why did fill rate drop on June 23?"* — or ask nothing at all and let it sweep the data
itself — and it answers in three steps:

1. **Detect** — is this window genuinely unusual, or ordinary noise?
2. **Decompose** — `Revenue = Requests × FillRate × eCPM`. Which factor actually moved?
3. **Drill down** — which segment inside that factor is responsible, and what was ruled out?

Against the four anomalies planted in the provided dataset, the drill-down scores **4/4**:

| Window | Metric | Answer | Change |
|---|---|---|---|
| Jun 23–25 | fill_rate | `os_version = Android 15` | 0.786 → 0.433 |
| Jun 19–22 | eCPM | `category = finance` | 2.478 → 1.613 |
| Jun 21 | requests | **no segment — population-wide** | −43.5% |
| Jun 28–30 | fill_rate | `region = APAC AND os_version = iOS 18.1` | 0.785 → 0.388 |

Two of those are the interesting ones. **Jun 21 must blame nobody** — that traffic collapse was
uniform across every region and every hour, so naming a culprit would be a false positive.
**Jun 28–30 only exists at an intersection**: iOS 18.1 alone is −12.7%, APAC alone is −4.4%, and
neither clears the bar. Only together do they reveal the real −50.4%.

## Architecture

```
                 ┌──────────── API ────────────┐
   browser ────▶ │ /investigate   /narrate     │
   LibreChat ──▶ │ /v1/chat/completions        │
                 └──────────────┬──────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              │           RCA ENGINE              │
              │  detection → decomposition        │
              │            → drill-down           │
              └─────────────────┬─────────────────┘
                                │  every step is SQL
                 ┌──────────────▼──────────────┐
                 │         CLICKHOUSE          │
                 │  events_full     9M rows    │
                 │  hourly_summary  rollup     │
                 │  investigations  evidence   │
                 └──────────────┬──────────────┘
                                │
                 ┌──────────────▼──────────────┐
                 │   NARRATOR — prose only     │
                 │   guardrail verifies every  │
                 │   number against the bundle │
                 └──────────────┬──────────────┘
                                │
                         Langfuse trace
```

Component-by-component detail: **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**.
The contract everything flows through: [`contracts/evidence_bundle.schema.json`](contracts/evidence_bundle.schema.json).

### Where the analysis runs

**All of it is in ClickHouse.** The drill-down issues a `GROUP BY` per dimension per depth and
ranks segments by a counterfactual: restore this segment's component sums to baseline, and how
much of the total metric gap closes? That fraction is then divided by the segment's share of the
metric's *volume* — its **lift**.

That ratio is the whole idea. A segment that is merely large closes roughly its own share of the
gap and scores lift ≈ 1. A real culprit closes far more than its share and scores much higher.
Ranking on raw contribution instead just picks whichever segment carries the most traffic — which
is how a naive drill-down "explains" Android 15 as *Android 15 AND tier_2 AND EU AND Galaxy A54*,
three extra conditions that explain nothing.

The LLM receives a finished Evidence Bundle and writes 3–5 sentences. It never queries, never
computes, and cannot inflate a figure: `narrator/guardrail.py` extracts every number from the
prose and rejects any absent from the bundle — including a genuine number wearing invented units,
so `18.33` written as `$18.33M` fails.

### Detection

Three interchangeable detectors behind one contract, selected via `config.detection.method`:

- **`robust_z`** — same weekday and hour over trailing weeks; median centre, MAD spread
- **`seasonal_ml`** — a per-(weekday × hour) profile from all history, scored on residuals
- **`isolation_forest`** — scikit-learn over a per-hour feature vector

Thresholds are **calibrated from the data**, not hardcoded (`data/calibration.py`): each metric's
floor derives from its own natural volatility, because "how big is big" differs wildly per metric.
Measured here, fill_rate settles near 2.8% while CTR needs 84% — there are only 74,940 clicks
across 9M events, so daily CTR is inherently noisy.

Detection runs on **every factor, not just revenue.** Jun 29–30 are the two highest-revenue days
in the dataset while APAC fill rate halved: traffic growth masked a real regression, and a
revenue-only detector never sees it.

### OSS Stack integration — Langfuse

Every investigation is one Langfuse trace, wired at the layer that matters:
`data.client.run_query` emits a span per SQL statement, nesting under the root automatically via
OpenTelemetry context. A judge reads the **actual query sequence**, not a summary of it.

`trace_id` is persisted alongside the bundle because `/investigate` and `/narrate` are separate
HTTP calls — without it the LLM generation opens an orphaned second trace and the SQL steps look
unrelated to the diagnosis. Chat turns group into a Langfuse **session**, so a whole conversation
reads as one thread.

`Query.langfuse_span_id` cross-references both ways: pick any number in a diagnosis, jump to the
span that produced it, and back again.

**LibreChat** is wired through an OpenAI-compatible endpoint. `POST /v1/chat/completions` returns
a valid chat completion with the Evidence Bundle riding alongside in the same payload, so one
endpoint serves both LibreChat and the dashboard with no adapter and no duplicated logic. Config
committed at [`librechat.yaml`](librechat.yaml) (no real keys).

## Tech stack

| Layer | |
|---|---|
| Analytics | **ClickHouse Cloud** — 9M ad events; single datastore for data *and* results |
| Backend | Python 3.11, FastAPI, `clickhouse-connect`, Pydantic, pandas, scikit-learn |
| Narration | AWS Bedrock, authenticated by IAM instance profile — no keys on the host |
| Observability | **Langfuse** v3, self-hosted |
| Chat | **LibreChat**, via the OpenAI-compatible endpoint |
| Dashboard | React 19 + TypeScript + Vite, served by nginx |
| Deployment | Docker Compose on EC2, nginx + Let's Encrypt, secrets in SSM Parameter Store |

**241 tests**, including a regression suite pinning all four planted anomalies to their exact
expected segments — the Jun 21 case asserts the system names *no* segment.

## Run it locally

```bash
git clone https://github.com/Rohanmrao/Clickathon2026.git
cd Clickathon2026
cp .env.example .env          # fill CLICKHOUSE_* ; Langfuse dev keys are pre-filled
docker compose up --build
```

Then open **http://localhost:5173**. Full notes, including loading the dataset, in
[`docs/docker.md`](docs/docker.md).

Backend only:

```bash
cd backend
pip install -e ".[dev]"
python -m data.load                    # 9M-row parquet + 3 CSVs into ClickHouse
uvicorn api.main:app --port 8000       # dev console at /dev, API docs at /docs
pytest -q
```

`GET /health` reports whether the engine is live and Langfuse is wired — the fastest way to tell
a half-started stack from a working one.

### API

```
GET  /health                    engine + Langfuse status
GET  /bundles                   investigation history
POST /investigate               run one — bundle in ~2s, no narrative, no LLM in the path
POST /narrate/{id}              add the prose, reattached to the same trace
GET  /bundle/{id}               retrieve stored evidence
POST /v1/chat/completions       OpenAI-compatible; LibreChat points here
GET  /chat/sessions             past conversations with history
```

`/investigate` is deliberately LLM-free so it can be called twice and diffed: same input, same
bundle.

```bash
curl -X POST https://clickathon.kangasys.com/api/investigate \
  -H 'Content-Type: application/json' \
  -d '{"metric":"fill_rate","window":{"start":"2026-06-23T00:00:00","end":"2026-06-26T00:00:00"}}'
```

## Deployment

A single EC2 host running Docker Compose behind nginx with Let's Encrypt.

Secrets live in **SSM Parameter Store** as `SecureString` and are read at boot through the
instance's IAM role — never in the repo, never in the image, never an AWS key on the box.
Rotating a credential is: update the parameter, reboot. The IAM policy is scoped to
`/clickathon/*` only, with `kms:Decrypt` gated by `kms:ViaService`.

Fully reproducible from [`deploy/`](deploy/) — bootstrap script, IAM policy, nginx config, README.

## Known limitations

Stated plainly, because trustworthiness is the point.

- **The unseen-incident bundle is not yet included.** Added when the fresh slice is released.
- **`/chat` detects but does not localize.** The conversational path runs a detection-only
  pipeline, so it reports the move without naming the segment; `/investigate` does the full
  drill-down. Being unified.
- **Global discovery is weaker than targeted investigation.** Handed a window, drill-down scores
  4/4. Sweeping blind, only anomalies large enough to move the whole population surface — a 50%
  collapse confined to 2% of traffic reads as −1% overall. Per-segment scanning addresses this
  and is partially in place.
- **Langfuse trace links currently require a login.** Programmatic publishing did not take effect
  on this Langfuse version; individual traces can be shared from the UI.

## Repository

```
backend/   rca/        detection, decomposition, drilldown, incidents
           narrator/   narrate, guardrail, tracing
           api/        endpoints, chat, pipeline
           data/       load, store, client, calibration
frontend/  React dashboard
deploy/    EC2 bootstrap, IAM policy, nginx config
docs/      ARCHITECTURE.md, docker.md
InMobi/    problem statement and synthetic dataset (read-only)
```

MIT licensed. All code written during the hackathon period.
