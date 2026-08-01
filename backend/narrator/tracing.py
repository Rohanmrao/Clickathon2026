"""Lane C: Langfuse tracing. One trace per investigation, one span per SQL, one generation span.

The trace is a scored deliverable ("no trace, no credit"). Degrades to a no-op if keys are unset
so the pipeline still runs locally.
"""
from __future__ import annotations

from contextlib import contextmanager

from config import LANGFUSE


def _client():
    if not LANGFUSE["public_key"]:
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=LANGFUSE["public_key"],
        secret_key=LANGFUSE["secret_key"],
        host=LANGFUSE["host"],
    )


@contextmanager
def investigation_trace(investigation_id: str, metric: str):
    """Yield a handle used to log query spans + the narration generation, and expose trace_url."""
    client = _client()
    # TODO(Lane C): open a trace keyed by investigation_id; yield an object with
    #   .query_span(query) and .generation(bundle, prose); set .url from the created trace.
    yield _NoopTrace()
    if client:
        client.flush()


class _NoopTrace:
    url: str | None = None

    def query_span(self, query: dict) -> None: ...
    def generation(self, bundle, prose: str) -> None: ...
