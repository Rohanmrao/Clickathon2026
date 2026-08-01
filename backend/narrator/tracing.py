"""Lane C: Langfuse tracing. One trace per investigation; query spans (emitted inside
`data.client.run_query`) nest under it automatically via OpenTelemetry context.

The trace is a scored deliverable ("no trace, no credit"). Degrades to a no-op if Langfuse
keys are unset so the pipeline still runs locally.
"""
from __future__ import annotations

from contextlib import contextmanager

from obs import langfuse


@contextmanager
def investigation_trace(
    investigation_id: str, metric: str, session_id: str | None = None
):
    """Open one trace per investigation. Yields the Langfuse trace_url (None if tracing disabled).

    Every `run_query` call made inside this context becomes a child span of this trace, and the
    session_id is propagated to the root span and all child spans so related investigations group
    under one session in Langfuse. Falls back to investigation_id when no session_id is given.
    """
    lf = langfuse()
    if lf is None:
        yield None
        return

    from langfuse import propagate_attributes

    session_id = session_id or investigation_id
    with propagate_attributes(session_id=session_id, trace_name=f"investigation:{metric}"):
        with lf.start_as_current_observation(
            name=f"investigation:{metric}", as_type="span"
        ) as root:
            root.update(
                input={
                    "investigation_id": investigation_id,
                    "metric": metric,
                    "session_id": session_id,
                }
            )
            trace_id = lf.get_current_trace_id()
            try:
                yield lf.get_trace_url(trace_id=trace_id)
            finally:
                lf.flush()
