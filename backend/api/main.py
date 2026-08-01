"""Lane C: FastAPI orchestration.

Endpoint surface (docs/superpowers/specs/2026-08-01-rca-api-design.md):

    GET  /health                    liveness
    GET  /bundle/{id}               retrieve a stored Evidence Bundle
    GET  /bundles                   investigation history
    POST /investigate               run the pipeline (still fixture-backed)
    POST /v1/chat/completions       conversational entry point; LibreChat points here

  uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api import chat as chatlib
from api import pipeline
from config import LANGFUSE
from api import dev
from data import store
from models import EvidenceBundle, Window

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
    """Wiring dashboard, not just liveness.

    Judges run this stack locally, where the failure modes are silent: a fresh Langfuse has no
    API keys and tracing quietly no-ops, and the RCA engine may still be stubbed. Reporting
    both here means a judge sees what is actually live before drawing conclusions from it.
    """
    return {
        "ok": True,
        "engine": pipeline.engine_status(),          # live | fixture
        "langfuse": {
            "enabled": bool(LANGFUSE["public_key"]),
            "host": LANGFUSE["host"],
        },
    }


@app.post("/investigate", response_model=EvidenceBundle)
def investigate(req: InvestigateRequest) -> EvidenceBundle:
    """Run an investigation and return the bundle WITHOUT a narrative.

    No LLM sits in this path, so a judge can call it twice and diff the result to verify
    reproducibility. Narration is POST /narrate/{id}.
    """
    return pipeline.run_investigation(req.metric, req.window)


@app.post("/narrate/{investigation_id}", response_model=EvidenceBundle)
def narrate_bundle(investigation_id: str) -> EvidenceBundle:
    """Add prose to a stored investigation.

    Split from /investigate so the UI shows real numbers in ~2s and only then the sentence
    arrives. The generation span reattaches to the trace the investigation already opened, so
    a judge reads one investigation rather than two unrelated traces.

    An LLM failure returns 200 with `narrative: null` rather than an error: the numbers,
    drilldown and ruled-out list are already computed and scoreable, so a Bedrock outage
    degrades the answer instead of losing it.
    """
    bundle = pipeline.narrate_investigation(investigation_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")
    return bundle


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


# ---------------------------------------------------------------------------
# Conversational layer (JAL-82). LibreChat points a custom endpoint at this.
# ---------------------------------------------------------------------------

def _run_investigation(slots: chatlib.Slots, session_id: str) -> EvidenceBundle:
    """Run the pipeline for a set of filled slots.

    Goes through the same `pipeline.run_investigation` as POST /investigate, so chat-driven
    investigations are traced and persisted identically - the session_id additionally groups
    every trace from one conversation together in Langfuse.
    """
    window = None
    if slots.window_start:
        window = Window(start=slots.window_start, end=slots.window_end or slots.window_start)
    return pipeline.run_investigation(slots.metric or "revenue", window, session_id=session_id)


def _diagnosis_text(bundle: EvidenceBundle) -> str:
    """Narrative plus a compact evidence summary.

    LibreChat renders only this string, so the evidence has to travel inside it - a judge
    reading the conversation should see the localized segment and what was ruled out without
    opening the dashboard.
    """
    lines = [bundle.narrative or "(no narrative generated)"]
    if bundle.localized_segment:
        segment = " AND ".join(f"{k}={v}" for k, v in bundle.localized_segment.items())
        lines.append(f"\n**Localized to:** {segment}")
    if bundle.ruled_out:
        lines.append("\n**Checked and ruled out:**")
        lines += [f"- {r.hypothesis}: {r.evidence}" for r in bundle.ruled_out]
    footer = f"\n_investigation `{bundle.investigation_id}`_"
    if bundle.trace_url:
        footer += f" · [trace]({bundle.trace_url})"
    lines.append(footer)
    return "\n".join(lines)


def _handle_chat(req: chatlib.ChatCompletionRequest, context_id: str) -> dict:
    slots = chatlib.fill_slots(req)
    intent = chatlib.classify(req, slots)

    store.upsert_session(context_id)
    if req.last_user_message():
        store.add_turn(context_id, "user", req.last_user_message())

    if intent == "greeting":
        content = ("I investigate metric anomalies. Ask me something like "
                   "\"why did revenue drop on June 23?\" and I'll find the responsible segment.")
    elif intent == "scan":
        content = ("Ask me about a specific metric and period and I'll investigate - "
                   "for example \"why did fill rate drop on June 23?\".")
    elif intent == "followup":
        content = chatlib.ask_for_missing(slots)
    else:
        bundle = _run_investigation(slots, context_id)  # traced + persisted inside
        payload = chatlib.completion(
            _diagnosis_text(bundle), context_id=context_id, slots=slots,
            investigation=bundle.model_dump(mode="json"),
            verification=bundle.narrative_verification.model_dump()
            if bundle.narrative_verification else None,
            plot_kind="metric_tree",
            plot_data=[n.model_dump(mode="json") for n in bundle.drilldown],
        )
        store.add_turn(context_id, "assistant", payload["choices"][0]["message"]["content"])
        return payload

    payload = chatlib.completion(content, context_id=context_id, slots=slots)
    store.add_turn(context_id, "assistant", content)
    return payload


def _sse(payload: dict):
    """Stream a finished completion as OpenAI-style SSE.

    The analysis is never streamed - it runs to completion first, then the text is chunked.
    Deterministic work does not belong in a token stream.
    """
    content = payload["choices"][0]["message"]["content"]
    head = {k: payload[k] for k in ("id", "object", "created", "model")}
    head["object"] = "chat.completion.chunk"
    for word in content.split(" "):
        chunk = head | {"choices": [{"index": 0, "delta": {"content": word + " "},
                                     "finish_reason": None}]}
        yield f"data: {json.dumps(chunk)}\n\n"
    final = head | {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
def chat_completions(
    req: chatlib.ChatCompletionRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    """OpenAI-compatible chat. LibreChat points a custom endpoint here.

    Both paths are registered because LibreChat's baseURL may or may not already include /v1.
    """
    context_id = x_session_id or req.conversation_id or str(uuid.uuid4())
    payload = _handle_chat(req, context_id)
    if req.stream:
        return StreamingResponse(_sse(payload), media_type="text/event-stream")
    return payload
