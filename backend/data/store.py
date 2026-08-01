"""JAL-73: system of record for investigations and chat sessions.

ClickHouse is the single datastore, so completed Evidence Bundles live here rather than on
disk or in memory. That keeps investigation history queryable in SQL, survives restarts, and
gives GET /bundle/{id} something to read.

`trace_id` is persisted because POST /investigate and POST /narrate/{id} are separate HTTP
calls. Narration must attach its generation span to the trace the investigation already
opened; without the stored id it would start an orphaned second trace and the SQL steps
would look unrelated to the LLM call.

Row mapping (`_to_row` / `_bundle_from_row`) is pure and unit-tested without a database.
Reads and writes here use the raw client rather than `data.client.run_query`, because
bookkeeping should not appear as analysis spans inside an investigation trace.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from data.client import get_client
from models import EvidenceBundle

INVESTIGATIONS = "investigations"
SESSIONS = "chat_sessions"
TURNS = "chat_turns"

_COLUMNS = [
    "investigation_id", "trace_id", "session_id", "created_at", "updated_at",
    "metric", "window_start", "window_end", "primary_factor", "localized_segment",
    "detected", "narrated", "bundle",
]


def _now() -> datetime:
    # ClickHouse DateTime is naive; store UTC without tzinfo so round-trips compare equal.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# ---- pure row mapping ------------------------------------------------------

def _to_row(bundle: EvidenceBundle, trace_id: str | None, session_id: str | None) -> list[Any]:
    """Flatten a bundle into an `investigations` row, ordered to match _COLUMNS."""
    return [
        bundle.investigation_id,
        trace_id or "",
        session_id or "",
        _naive(bundle.created_at),
        _now(),
        bundle.metric,
        _naive(bundle.target_window.start),
        _naive(bundle.target_window.end),
        bundle.factor_decomposition.primary_factor if bundle.factor_decomposition else "",
        json.dumps(bundle.localized_segment or {}),
        1 if bundle.anomaly.detected else 0,
        1 if bundle.narrative else 0,
        bundle.model_dump_json(),
    ]


def _bundle_from_row(row: dict[str, Any]) -> EvidenceBundle:
    """Rehydrate the bundle. The `bundle` column is the source of truth; the flattened
    columns exist only so the table is queryable in SQL."""
    return EvidenceBundle.model_validate_json(row["bundle"])


# ---- investigations --------------------------------------------------------

def save_bundle(
    bundle: EvidenceBundle, trace_id: str | None = None, session_id: str | None = None
) -> None:
    """Insert or replace the row for this investigation_id (ReplacingMergeTree)."""
    get_client().insert(INVESTIGATIONS, [_to_row(bundle, trace_id, session_id)], column_names=_COLUMNS)


def load_bundle(investigation_id: str) -> EvidenceBundle | None:
    rows = get_client().query(
        f"SELECT bundle FROM {INVESTIGATIONS} FINAL WHERE investigation_id = {{id:String}}",
        parameters={"id": investigation_id},
    ).result_rows
    return EvidenceBundle.model_validate_json(rows[0][0]) if rows else None


def load_trace_id(investigation_id: str) -> str | None:
    """The Langfuse trace opened by /investigate, so /narrate can attach to it."""
    return load_meta(investigation_id)[0]


def load_meta(investigation_id: str) -> tuple[str | None, str | None]:
    """(trace_id, session_id) for an existing investigation.

    Both must be re-supplied on any later write. `investigations` is a ReplacingMergeTree keyed
    on investigation_id, so a save that omits them does not merge — it replaces the row with
    empty strings and silently breaks two links: /narrate's trace reattachment, and the
    session -> investigation association that GET /chat/sessions/{id} depends on.
    """
    rows = get_client().query(
        f"SELECT trace_id, session_id FROM {INVESTIGATIONS} FINAL "
        f"WHERE investigation_id = {{id:String}}",
        parameters={"id": investigation_id},
    ).result_rows
    if not rows:
        return None, None
    return (rows[0][0] or None), (rows[0][1] or None)


def list_investigations(limit: int = 50) -> list[dict[str, Any]]:
    result = get_client().query(
        f"SELECT investigation_id, created_at, metric, window_start, window_end, "
        f"primary_factor, localized_segment, detected, narrated, trace_id, session_id "
        f"FROM {INVESTIGATIONS} FINAL ORDER BY created_at DESC LIMIT {{n:UInt32}}",
        parameters={"n": limit},
    )
    return [dict(zip(result.column_names, r)) for r in result.result_rows]


# ---- chat sessions ---------------------------------------------------------

def upsert_session(context_id: str, title: str | None = None) -> None:
    now = _now()
    existing = get_client().query(
        f"SELECT created_at, title FROM {SESSIONS} FINAL WHERE context_id = {{id:String}}",
        parameters={"id": context_id},
    ).result_rows
    created = existing[0][0] if existing else now
    resolved = title if title is not None else (existing[0][1] if existing else "")
    get_client().insert(
        SESSIONS, [[context_id, resolved, created, now]],
        column_names=["context_id", "title", "created_at", "updated_at"],
    )


def add_turn(context_id: str, role: str, message: str) -> None:
    get_client().insert(
        TURNS, [[context_id, role, message, _now()]],
        column_names=["context_id", "role", "message", "created_at"],
    )


def get_turns(context_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Oldest-first, capped to the most recent `limit` turns."""
    result = get_client().query(
        f"SELECT role, message, created_at FROM ("
        f"  SELECT role, message, created_at FROM {TURNS} WHERE context_id = {{id:String}} "
        f"  ORDER BY created_at DESC LIMIT {{n:UInt32}}"
        f") ORDER BY created_at ASC",
        parameters={"id": context_id, "n": limit},
    )
    return [dict(zip(result.column_names, r)) for r in result.result_rows]


def list_sessions(limit: int = 100) -> list[dict[str, Any]]:
    result = get_client().query(
        f"SELECT context_id, title, created_at, updated_at FROM {SESSIONS} FINAL "
        f"ORDER BY updated_at DESC LIMIT {{n:UInt32}}",
        parameters={"n": limit},
    )
    return [dict(zip(result.column_names, r)) for r in result.result_rows]


def delete_session(context_id: str) -> bool:
    client = get_client()
    exists = client.query(
        f"SELECT count() FROM {SESSIONS} FINAL WHERE context_id = {{id:String}}",
        parameters={"id": context_id},
    ).result_rows[0][0]
    if not exists:
        return False
    for table in (SESSIONS, TURNS):
        client.command(
            f"ALTER TABLE {table} DELETE WHERE context_id = {{id:String}}",
            parameters={"id": context_id},
        )
    return True


def delete_all_sessions() -> int:
    client = get_client()
    count = client.query(f"SELECT count() FROM {SESSIONS} FINAL").result_rows[0][0]
    for table in (SESSIONS, TURNS):
        client.command(f"TRUNCATE TABLE {table}")
    return count
