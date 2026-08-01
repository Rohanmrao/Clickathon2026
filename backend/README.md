# Backend

Python. Data + RCA + Narrator + API. Run all commands from `backend/`.

## Setup
```bash
uv venv && uv pip install -e ".[dev]"
cp ../.env.example ../.env   # then fill in creds
```

## Run the API (works today against the fixture)
```bash
uvicorn api.main:app --reload --port 8000
# POST http://localhost:8000/investigate  -> returns the sample Evidence Bundle
```

## Test
```bash
pytest -q
```

## Layout
- `config.py` / `config.json` — all thresholds, dimensions, table names. No magic strings in code.
- `models.py` — pydantic mirror of `contracts/evidence_bundle.schema.json`.
- `data/` — Lane A: `schema.sql`, `load.py`, `client.run_query`, `metrics.sql`.
- `rca/` — Lane B: `detection.py`, `decomposition.py`, `drilldown.py`, `bundle.py`.
- `narrator/` — Lane C: `narrate.py`, `guardrail.py` (working), `tracing.py`.
- `api/` — Lane C: `main.py`.

Stubs raise `NotImplementedError` and point to the owning lane's prompt in `prompts/`.
