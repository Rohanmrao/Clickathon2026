"""Build the advanced hourly rollup (config.clickhouse.hourly_table) from the enriched table.

Repeatable + idempotent:  `python -m data.build_advanced`  (drops then recreates).

Why a script and not static SQL: table names come from `config` and ratio formulas come from the
shared `metrics` lib, so this stays the ONE definition — no second copy in schema.sql to drift.
Stored columns = raw sums (requests/fills/impressions/clicks/revenue) + zero-safe ratios
(fill_rate/render_rate/ctr/ecpm/rpr). Ratios use ifNull(.. , 0) so a 0 denominator yields 0, not NULL.
Engine is MergeTree (NOT SummingMergeTree) — ratio columns must never be summed on merge.
"""
from __future__ import annotations

from config import config
from data.client import get_client, run_query
from metrics import metric_sql

_CFG = config()
_SRC = _CFG["clickhouse"]["enriched_table"]   # source: denormalized event rows (events_full)
_DST = _CFG["clickhouse"]["hourly_table"]     # target: metrics_hourly_advanced
_DIMS = _CFG["rca"]["drilldown_dimensions"]   # every drill-down dimension, in canonical order
_BASE = _CFG["metrics"]["base_events"]         # raw column exprs over raw event rows
_RATIOS = ["fill_rate", "render_rate", "ctr", "ecpm", "rpr"]


def _zero_safe(name: str) -> str:
    # metric_sql already guards divide-by-zero with nullIf -> NULL; ifNull turns that NULL into 0.
    return f"ifNull({metric_sql(name, 'events')}, 0)"


def build_sql() -> str:
    dims = ", ".join(_DIMS)
    raw = ", ".join(f"{expr} AS {name}" for name, expr in _BASE.items())   # count(*) AS requests, ...
    ratios = ", ".join(f"{_zero_safe(r)} AS {r}" for r in _RATIOS)
    return (
        f"CREATE TABLE {_DST} ENGINE = MergeTree ORDER BY (hour, {dims}) AS "
        f"SELECT toStartOfHour(event_time) AS hour, {dims}, {raw}, {ratios} "
        f"FROM {_SRC} GROUP BY ALL "
        # raw col `sum(revenue) AS revenue` shadows source column `revenue`; prefer the column so
        # ratio exprs read `sum(revenue)`, not `sum(sum(revenue))` (illegal nested aggregation).
        f"SETTINGS prefer_column_name_to_alias = 1"
    )


def main() -> None:
    client = get_client()
    client.command(f"DROP TABLE IF EXISTS {_DST}")
    client.command(build_sql())
    n = run_query(f"SELECT count() FROM {_DST}")["rows"][0][0]
    nulls = run_query(
        f"SELECT {' + '.join(f'countIf({r} IS NULL)' for r in _RATIOS)} FROM {_DST}"
    )["rows"][0][0]
    print(f"built {_DST} from {_SRC}: {n:,} rows, {nulls} NULL ratio cells")


if __name__ == "__main__":
    main()
