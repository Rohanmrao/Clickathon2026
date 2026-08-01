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
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api import chat as chatlib
from data import store
from models import EvidenceBundle, Window
from narrator.tracing import investigation_trace

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


# ---------------------------------------------------------------------------
# Conversational layer (JAL-82). LibreChat points a custom endpoint at this.
# ---------------------------------------------------------------------------

def _run_investigation(slots: chatlib.Slots, context_id: str) -> EvidenceBundle:
    """Run the pipeline for a set of filled slots, inside one Langfuse trace.

    The LibreChat conversation id (context_id) is the Langfuse session_id, so every turn of a
    chat thread groups under one session. Fixture-backed for now, exactly as /investigate is,
    so LibreChat and the dashboard can be wired and demoed before Lane B's engine lands.

    Swapping in the real pipeline changes only the body of the `with` block: build_bundle()'s
    run_query calls and narrate()'s LLM call will auto-nest as spans under this trace.
    """
    investigation_id = str(uuid.uuid4())
    metric = slots.metric or "revenue"
    with investigation_trace(investigation_id, metric, session_id=context_id) as trace_url:
        # TODO(JAL-79): build_bundle(metric, window) + narrate(...) HERE so SQL spans and the
        #   narration generation land in this trace.
        bundle = EvidenceBundle.model_validate(json.loads(FIXTURE.read_text()))
        bundle.investigation_id = investigation_id
        bundle.metric = metric
        if trace_url:
            bundle.trace_url = trace_url
    return bundle


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
    # LibreChat's title-generation call: answer it deterministically and return. No slot-fill,
    # no stored turn, no Langfuse investigation trace - a title is not an investigation.
    if chatlib.is_title_request(req):
        return chatlib.completion(
            chatlib.make_title(req), context_id=context_id, slots=chatlib.Slots()
        )

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
        bundle = _run_investigation(slots, context_id)
        store.save_bundle(bundle, session_id=context_id)
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
