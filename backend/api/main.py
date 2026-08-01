"""Lane C: FastAPI orchestration.

Endpoint surface (docs/superpowers/specs/2026-08-01-rca-api-design.md):

    GET  /health                liveness
    GET  /bundle/{id}           retrieve a stored Evidence Bundle
    GET  /bundles               investigation history
    POST /investigate           run the pipeline (still fixture-backed)

  uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import dev
from data import store
from models import EvidenceBundle, Window

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_bundle.json"

app = FastAPI(title="Automated Root-Cause Analyst")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# Dev/admin dashboard at /dev — local only, gated by env (default on). Never enable on a public deploy.
if dev.dev_enabled():
    app.include_router(dev.router)


class InvestigateRequest(BaseModel):
    metric: str = "revenue"
    window: Window | None = None


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/investigate", response_model=EvidenceBundle)
def investigate(req: InvestigateRequest) -> EvidenceBundle:
    # Ships against the fixture so the frontend and demo work from day one.
    # TODO(JAL-79): replace with build_bundle(req.metric, req.window), persist via
    #   store.save_bundle(bundle, trace_id=...), and return without a narrative.
    return EvidenceBundle.model_validate(json.loads(FIXTURE.read_text()))


@app.get("/bundle/{investigation_id}", response_model=EvidenceBundle)
def get_bundle(investigation_id: str) -> EvidenceBundle:
    """Retrieve a stored Evidence Bundle.

    This is how a judge re-reads an investigation after the fact, and it is the
    submission artifact path for the unseen incident.
    """
    bundle = store.load_bundle(investigation_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")
    return bundle


@app.get("/bundles")
def list_bundles(limit: int = 50) -> dict:
    """Investigation history — the flattened columns, not the full bundles.

    Lets the dashboard show past runs and lets a judge see what the system has
    investigated without pulling every bundle body.
    """
    rows = store.list_investigations(limit)
    return {"count": len(rows), "investigations": rows}
