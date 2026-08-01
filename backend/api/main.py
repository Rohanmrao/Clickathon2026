"""Lane C: FastAPI orchestration. Runs today against the fixture; swap to the live pipeline later.

  uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import EvidenceBundle, Window

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_bundle.json"

app = FastAPI(title="Automated Root-Cause Analyst")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class InvestigateRequest(BaseModel):
    metric: str = "revenue"
    window: Window | None = None


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/investigate", response_model=EvidenceBundle)
def investigate(req: InvestigateRequest) -> EvidenceBundle:
    # Ships against the fixture so the frontend and demo work from day one.
    # TODO(Lane C): replace with build_bundle(req.metric, req.window) -> narrate(...) -> attach trace_url.
    return EvidenceBundle.model_validate(json.loads(FIXTURE.read_text()))
