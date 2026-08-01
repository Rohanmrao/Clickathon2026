"""ClickHouse access. run_query returns rows AND the resolved SQL for queries[] traceability."""
from __future__ import annotations

import time
from typing import Any

import clickhouse_connect

from config import CLICKHOUSE
from obs import langfuse


def get_client():
    return clickhouse_connect.get_client(
        host=CLICKHOUSE["host"],
        port=CLICKHOUSE["port"],
        username=CLICKHOUSE["username"],
        password=CLICKHOUSE["password"],
        database=CLICKHOUSE["database"],
        secure=True,
    )


def run_query(
    sql: str, params: dict[str, Any] | None = None, name: str = "clickhouse-query"
) -> dict[str, Any]:
    """Run parameterized SQL. Returns {rows, columns, resolved_sql, elapsed_ms}.

    resolved_sql is what belongs in EvidenceBundle.queries[].sql — the traceability record.
    Each call is wrapped in a Langfuse span (input=SQL, output=result summary); when Langfuse
    is enabled the returned dict also carries langfuse_span_id for EvidenceBundle.queries[].
    """
    params = params or {}
    lf = langfuse()
    if lf is None:
        return _execute(sql, params)

    with lf.start_as_current_observation(name=name, as_type="span") as span:
        out = _execute(sql, params)
        span.update(
            input=out["resolved_sql"],
            output={
                "row_count": len(out["rows"]),
                "columns": out["columns"],
                "sample": out["rows"][:5],
            },
            metadata={"elapsed_ms": round(out["elapsed_ms"], 1)},
        )
        out["langfuse_span_id"] = span.id
    return out


def _execute(sql: str, params: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result = get_client().query(sql, parameters=params)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "rows": result.result_rows,
        "columns": result.column_names,
        "resolved_sql": _inline(sql, params),
        "elapsed_ms": elapsed_ms,
    }


def _inline(sql: str, params: dict[str, Any]) -> str:
    # Best-effort render of {name:Type} placeholders for logging only (never for execution).
    out = sql
    for key, value in params.items():
        out = out.replace(f"{{{key}:", f"/* {key}={value!r} */ {{{key}:")
    return out
