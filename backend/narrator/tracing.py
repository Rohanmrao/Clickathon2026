"""Lane C: Langfuse tracing. One trace per investigation; query spans (emitted inside
`data.client.run_query`) nest under it automatically via OpenTelemetry context.

The trace is a scored deliverable ("no trace, no credit"). Degrades to a no-op if Langfuse
keys are unset so the pipeline still runs locally.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from obs import langfuse


@dataclass(frozen=True)
class Trace:
    """Handle for one investigation's trace.

    `trace_id` is persisted alongside the bundle because POST /investigate and
    POST /narrate/{id} are separate HTTP calls: narration must attach its generation span to
    the trace the investigation already opened, or the SQL steps and the LLM call show up as
    two unrelated traces and the reasoning becomes unreadable.

    `url` is what a judge clicks. Both are None when tracing is disabled.
    """
    trace_id: str | None = None
    url: str | None = None

    @property
    def enabled(self) -> bool:
        return self.trace_id is not None


@contextmanager
def investigation_trace(
    investigation_id: str, metric: str, session_id: str | None = None
):
    """Open one trace per investigation. Yields a `Trace` (inert when tracing is disabled).

    Every `run_query` call made inside this context becomes a child span of this trace, and the
    session_id is propagated to the root span and all child spans so related investigations group
    under one session in Langfuse. Falls back to investigation_id when no session_id is given.
    """
    lf = langfuse()
    if lf is None:
        yield Trace()
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
                yield Trace(trace_id=trace_id, url=lf.get_trace_url(trace_id=trace_id))
            finally:
                lf.flush()


@contextmanager
def narration_span(trace_id: str | None, metric: str):
    """Attach the LLM generation to the trace the investigation already opened.

    POST /investigate and POST /narrate/{id} are separate HTTP calls, so without the stored
    trace_id the narration would start its own trace and a judge would see the SQL steps and
    the LLM call as two unrelated investigations.

    Yields the span (or None when tracing is off) so the caller can attach the prompt, the
    prose and the guardrail verdict. Reattachment is attempted defensively: if the installed
    Langfuse SDK does not accept an explicit trace context, we fall back to an unparented span
    rather than losing the narration entirely.
    """
    lf = langfuse()
    if lf is None:
        yield None
        return

    kwargs = {"name": f"narrate:{metric}", "as_type": "generation"}
    try:
        cm = (lf.start_as_current_observation(trace_context={"trace_id": trace_id}, **kwargs)
              if trace_id else lf.start_as_current_observation(**kwargs))
    except TypeError:  # SDK without trace_context support
        cm = lf.start_as_current_observation(**kwargs)

    with cm as span:
        try:
            yield span
        finally:
            lf.flush()
