"""Lane B (JAL-37): assemble a schema-valid EvidenceBundle from detection + decomposition + drill-down.

This is the object the whole system flows through — the RCA engine produces it, the Narrator and
Dashboard consume it. Every number in it must trace to a query in `queries`. The flow:

    incident scan (window + anomaly)  ->  decompose (which factor)  ->  drill (which segment)
                                       ->  ruled_out (flat factors)  ->  EvidenceBundle

narrative / trace_url are filled later by Lane C.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from config import config
from data.client import run_query
from metrics import metric_sql
from models import (
    Anomaly,
    BaselineWindow,
    EvidenceBundle,
    FactorDecomposition,
    RuledOut,
    Window,
)
from rca.decomposition import decompose
from rca.drilldown import baseline_window, drill
from rca.incidents import scan_incidents

_RCA = config()["rca"]
_HOURLY = config()["clickhouse"]["hourly_table"]
_FLAT_MAX = 0.2  # |contribution_pct| below this => the factor is flat -> ruled out

# Map an identity factor to the ruled-out hypothesis name the narrator/schema expect.
_HYPOTHESIS = {"requests": "request_volume", "fill_rate": "fill_rate",
               "render_rate": "render_rate", "ecpm": "ecpm_price"}


def build_bundle(metric: str, target: Window | None = None) -> EvidenceBundle:
    """Run one investigation into a schema-valid EvidenceBundle (no narrative — that's Lane C)."""
    window, anomaly, q_detect = _window_and_anomaly(metric, target)
    baseline = baseline_window(window)

    factors, q_decomp = decompose(metric, window, baseline)
    # Revenue investigations drill the factor that moved; a direct-metric investigation drills itself.
    factor = factors.primary_factor if metric == "revenue" else metric
    path, localized, q_drill = drill(metric, factor, window, baseline)
    ruled = _ruled_out(factors, q_decomp[0]["id"])

    return EvidenceBundle(
        investigation_id=str(uuid.uuid4()),
        created_at=datetime.now(UTC),
        metric=metric,
        target_window=window,
        baseline_window=BaselineWindow(
            method="same_weekday_trailing_weeks",
            description=f"same window shifted back {_RCA['baseline_weeks']} weeks (weekday-aligned)",
            weeks=_RCA["baseline_weeks"],
        ),
        anomaly=anomaly,
        factor_decomposition=factors,
        drilldown=path,
        localized_segment=localized,
        ruled_out=ruled,
        queries=[*q_detect, *q_decomp, *q_drill],
    )


# ---- window + anomaly (incident scan, with a not-detected fallback) ---------

def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _data_range() -> tuple[datetime, datetime]:
    row = run_query(
        f"SELECT toStartOfDay(min(hour)), toStartOfDay(max(hour)) + INTERVAL 1 DAY FROM {_HOURLY}"
    )["rows"][0]
    return row[0], row[1]


def _metric_over(metric: str, w: Window) -> tuple[float, str]:
    sql = (f"SELECT {metric_sql(metric, 'rollup')} FROM {_HOURLY} "
           f"WHERE hour >= toDateTime({{s:String}}) AND hour < toDateTime({{e:String}})")
    res = run_query(sql, {"s": _fmt(w.start), "e": _fmt(w.end)})
    return float(res["rows"][0][0] or 0.0), res["resolved_sql"]


def _window_and_anomaly(metric: str, target: Window | None) -> tuple[Window, Anomaly, list[dict]]:
    """Find the incident window + its anomaly. If nothing fires globally, keep the requested window
    and report a not-detected anomaly from the window aggregate (drill can still localise it)."""
    lo, hi = (target.start, target.end) if target else _data_range()
    scan = scan_incidents(lo, hi, metrics=[metric], grain="day")
    incident = next((i for i in scan.incidents if i.metric == metric), None)

    if incident is not None:
        window = Window(start=incident.window_start, end=incident.window_end)
        anomaly = Anomaly(
            detected=True, observed=incident.observed, expected=incident.expected,
            abs_delta=incident.observed - incident.expected, pct_delta=incident.peak_pct_delta,
            score=incident.peak_z, direction=incident.direction,
        )
        return window, anomaly, list(scan.queries)

    window = target or Window(start=lo, end=hi)
    observed, sql_obs = _metric_over(metric, window)
    expected, sql_exp = _metric_over(metric, baseline_window(window))
    anomaly = Anomaly(
        detected=False, observed=observed, expected=expected, abs_delta=observed - expected,
        pct_delta=(observed - expected) / expected if expected else 0.0, score=0.0,
        direction="drop" if observed < expected else "spike",
    )
    q_obs = {"id": "q_observed", "sql": sql_obs, "result_summary": {"observed": observed}}
    q_exp = {"id": "q_expected", "sql": sql_exp, "result_summary": {"expected": expected}}
    return window, anomaly, [*scan.queries, q_obs, q_exp]


# ---- ruled_out (flat, non-primary factors) — pure --------------------------

def _ruled_out(factors: FactorDecomposition, query_id: str) -> list[RuledOut]:
    out = []
    for f in factors.factors:
        if f.factor == factors.primary_factor or abs(f.contribution_pct) >= _FLAT_MAX:
            continue
        out.append(RuledOut(
            hypothesis=_HYPOTHESIS.get(f.factor, f.factor),
            evidence=f"{f.factor} contributed {f.contribution_pct * 100:.1f}% of the change "
                     f"({f.from_:.4g} -> {f.to:.4g}) — within noise",
            query_id=query_id,
        ))
    return out
