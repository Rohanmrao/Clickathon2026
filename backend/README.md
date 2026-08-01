# Backend

Python backend for the automated RCA analyst: **data** (ClickHouse), **RCA**, **narrator**, **API**.

> Run every command from **`backend/`**. Running from the repo root lets the root `config/` folder
> shadow `backend/config.py`, breaking imports.

## Prerequisites
- Python **3.11+** (`python --version`)
- ClickHouse Cloud credentials (see [Environment](#environment))
- No `uv` required — plain `venv` + `pip` is fine.

## Setup (once)
PowerShell 5.1 has no `&&`, so run these as separate lines:
```bash
python -m venv .venv                 # create the virtualenv
.venv\Scripts\Activate.ps1           # activate it — prompt should show (.venv)
python -m pip install -e ".[dev]"    # install the package + dev deps (pytest, ruff)
```
If activation is blocked by execution policy, allow it for this shell only:
```bash
Set-ExecutionPolicy -Scope Process -Bypass
```

## Environment
Table names and thresholds live in `config.json` (no magic strings in code). **Secrets** live in a
`.env` file at the **repo root** (one level up from `backend/`):
```bash
cp ../.env.example ../.env           # then fill in the values
```
Required keys: `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`,
`CLICKHOUSE_DATABASE`.

## Run the tests (no database needed)
The suite covers metric formulas, the robust stats, and the baseline engine against fixed inputs:
```bash
pytest -q                            # all tests
pytest tests/test_baseline.py -v     # just the baseline engine, verbose
```

## Load the data / build the tables
Lane A loads the four source files and builds the derived tables. `hourly_summary` is the hourly
rollup the RCA engine reads (`config.clickhouse.hourly_table`) — it stores raw sums, and ratios are
computed at read time (sum/sum) by the shared `metrics` lib:
```bash
python -m data.load                  # ad_events + *_dim -> events_full -> hourly_summary, then sanity-checks
```
> DDL lives in [`data/schema.sql`](data/schema.sql); the loader is [`data/load.py`](data/load.py).

## Run a baseline query (live, against ClickHouse)
`score()` = one metric on one segment; `scan()` = every value of a dimension, ranked by |robust_z|:
```bash
# global revenue baseline for one hour (same weekday + hour over the trailing 3 weeks)
python -c "from datetime import datetime; from rca import baseline; s=baseline.score('revenue', datetime(2026,7,4,10)).stats[0]; print('observed=%.2f expected=%.2f z=%.2f detected=%s' % (s.observed, s.expected, s.robust_z, s.detected))"

# top-5 countries by anomaly strength for revenue at that hour
python -c "from datetime import datetime; from rca import baseline; r=baseline.scan('revenue', datetime(2026,7,4,10), 'country'); [print(s.segment, round(s.robust_z,2), s.detected) for s in r.stats[:5]]"
```

## Run the API
```bash
uvicorn api.main:app --reload --port 8000
# POST http://localhost:8000/investigate  -> Evidence Bundle
```

## Inspect the database (ad-hoc)
```bash
python -c "from data.client import run_query; print([r[0] for r in run_query('SHOW TABLES')['rows']])"
```

## Layout
- `config.py` / `config.json` — all thresholds, dimensions, table names. No magic strings in code.
- `metrics.py` — the ONE place metric formulas live (SQL builders + Python compute).
- `models.py` — pydantic mirror of `contracts/evidence_bundle.schema.json`.
- `data/` — Lane A: `schema.sql`, `load.py`, `client.run_query`, `metrics.sql`.
- `rca/` — Lane B: `baseline.py`, `detection.py`, `decomposition.py`, `drilldown.py`, `bundle.py`.
- `narrator/` — Lane C: `narrate.py`, `guardrail.py`, `tracing.py`.
- `api/` — Lane C: `main.py`.

Stubs raise `NotImplementedError` and point to the owning lane's prompt in `prompts/`.

## Live table names
The live ClickHouse and this repo agree on these names (config-driven):
`ad_events`, `apps_dim`, `advertisers_dim`, `geo_device_dim`, `events_full` (enriched),
`hourly_summary` (rollup).
