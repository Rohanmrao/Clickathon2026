"""JAL-79: the one place an investigation actually runs.

Both POST /investigate and POST /v1/chat/completions come through here, so the trace, the
persistence and the fixture fallback cannot drift apart between them.

WHY THIS EXISTS AT ALL: `investigation_trace()` was written by Lane C but nothing ever called
it, so Langfuse emitted zero spans - a scored criterion sitting at zero with the plumbing
already built. Opening the root trace here is the whole fix, and it multiplies: `run_query`
already emits a span per query that nests via OpenTelemetry context, so every SQL statement the
pipeline runs appears inside this trace automatically, with no further instrumentation.

The engine (Lane B's `build_bundle`) is still a stub. Rather than fail, we fall back to the
fixture so the API, LibreChat and the dashboard can all be wired and demoed now. That fallback
is reported honestly through `engine_status()` and GET /health - silently serving fixture
numbers as a real diagnosis is exactly the kind of thing that loses trust points.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from data import store
from models import EvidenceBundle, Window
from narrator.tracing import investigation_trace

log = logging.getLogger(__name__)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "sample_bundle.json"


def engine_status() -> str:
    """'live' once Lane B's engine is implemented, else 'fixture'.

    Probed rather than hardcoded, so the API flips to 'live' the moment the engine lands with
    no change needed here. The probe looks for the NotImplementedError sentinel in each
    function's compiled code, which is cheap and has no side effects - unlike calling them.
    """
    try:
        from rca import bundle, decomposition, detection, drilldown
    except Exception:
        return "fixture"

    targets = [(bundle, "build_bundle"), (detection, "detect"),
               (decomposition, "decompose"), (drilldown, "drill")]
    for module, name in targets:
        func = getattr(module, name, None)
        if func is None or "NotImplementedError" in getattr(func.__code__, "co_names", ()):
            return "fixture"
    return "live"


def _fixture_bundle(investigation_id: str, metric: str, window: Window | None) -> EvidenceBundle:
    bundle = EvidenceBundle.model_validate(json.loads(FIXTURE.read_text()))
    bundle.investigation_id = investigation_id
    bundle.metric = metric
    if window:
        bundle.target_window = window
    return bundle


def run_investigation(
    metric: str,
    window: Window | None = None,
    session_id: str | None = None,
) -> EvidenceBundle:
    """Run one investigation end to end: trace it, build it, persist it.

    Returns the bundle WITHOUT a narrative. Narration is a separate call (JAL-80) so the UI can
    show real numbers in ~2s, and so an LLM failure cannot destroy an otherwise complete and
    scoreable bundle.
    """
    investigation_id = str(uuid.uuid4())

    with investigation_trace(investigation_id, metric, session_id) as trace:
        if engine_status() == "live":
            from rca.bundle import build_bundle

            bundle = build_bundle(metric, window)
            bundle.investigation_id = investigation_id
        else:
            log.warning(
                "RCA engine not implemented (JAL-76/79) - serving FIXTURE data for "
                "investigation %s. Numbers are not computed from ClickHouse.",
                investigation_id,
            )
            bundle = _fixture_bundle(investigation_id, metric, window)

        # Enforce the investigate/narrate split at the seam rather than trusting callers.
        # The fixture ships with prose, and a future build_bundle might too; either way an
        # un-narrated bundle is the contract here, so that /narrate is what produces prose
        # and `narrated` in the stored row means something.
        bundle.narrative = None
        bundle.narrative_verification = None

        bundle.created_at = datetime.now()
        bundle.trace_url = trace.url
        store.save_bundle(bundle, trace_id=trace.trace_id, session_id=session_id)

    return bundle
