"""JAL-78: find incidents without being told where to look.

The unseen-incident deliverable gives us a fresh data slice and nobody knows which window is
anomalous, so the system has to sweep the data itself. Two things this module exists to get
right, both of which a naive scanner gets wrong:

1. SCAN EVERY FACTOR, NOT REVENUE. Revenue is the headline metric but it hides things. In the
   provided data, Jun 29-30 are the two highest-revenue days in the whole 35-day set while APAC
   fill rate collapsed by half - traffic growth masked it completely. Detection therefore runs
   independently on requests, fill_rate, render_rate, ecpm, ctr and revenue.

2. MERGE CONTIGUOUS WINDOWS. Planted anomalies span days. At hourly grain a single 3-day
   anomaly fires ~72 separate alerts, and investigating each one produces 72 near-identical
   bundles. Adjacent flagged buckets collapse into one incident before anything is investigated.

Cost is one query per metric for an entire scan: a single pass pulls the target range plus the
trailing history, and the like-for-like comparison happens in Python over that small series.

The detection rule is deliberately imported from `rca.baseline` rather than reimplemented, so
there is exactly one definition of "is this an anomaly" in the codebase.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config import config
from data.client import run_query
from metrics import metric_sql
from rca.baseline import _detected
from rca.robust import mad, med, pct_delta, robust_z

_CFG = config()
_DET = _CFG["detection"]
_HOURLY = _CFG["clickhouse"]["hourly_table"]

# Revenue alone is not enough (see module docstring). Overridable via config.
DEFAULT_METRICS = _CFG["rca"].get(
    "incident_scan_metrics",
    ["revenue", "requests", "fill_rate", "render_rate", "ecpm", "ctr"],
)

_GRAIN_SQL = {"day": "toStartOfDay(hour)", "hour": "toStartOfHour(hour)"}
_GRAIN_STEP = {"day": timedelta(days=1), "hour": timedelta(hours=1)}

# Minimum relative move before an incident is surfaced. Deliberately delegated to the
# detection config that Lane B owns (JAL-74) rather than tuned here - this module decides
# how buckets are grouped and ranked, not what counts as an anomaly.
MIN_EFFECT = _DET["min_pct_delta"]


@dataclass
class Bucket:
    """One time bucket of one metric, scored against its like-for-like baseline."""
    bucket: datetime
    observed: float
    expected: float
    robust_z: float
    pct_delta: float
    requests: int
    detected: bool


@dataclass
class Incident:
    metric: str
    window_start: datetime
    window_end: datetime          # exclusive
    direction: str                # drop | spike
    peak_z: float
    peak_pct_delta: float
    observed: float               # value at the peak bucket
    expected: float               # baseline at the peak bucket
    affected_requests: int
    buckets: int
    score: float                  # ranking: severity weighted by volume

    def incident_id(self) -> str:
        return f"{self.metric}:{self.window_start:%Y-%m-%dT%H}"

    def as_dict(self) -> dict:
        return {
            "incident_id": self.incident_id(),
            "metric": self.metric,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "direction": self.direction,
            "peak_z": round(self.peak_z, 2),
            "peak_pct_delta": round(self.peak_pct_delta, 4),
            "observed": self.observed,
            "expected": self.expected,
            "affected_requests": self.affected_requests,
            "buckets": self.buckets,
            "score": round(self.score, 1),
        }


@dataclass
class ScanResult:
    incidents: list[Incident]
    queries: list[dict] = field(default_factory=list)


# ---- pure logic (unit-tested without a database) ---------------------------

def merge_windows(
    flagged: list[datetime], step: timedelta, max_gap: int = 1
) -> list[tuple[datetime, datetime]]:
    """Collapse adjacent flagged buckets into (start, end-exclusive) windows.

    `max_gap` tolerates short recoveries inside one incident: with max_gap=1 a single clean
    bucket between two flagged ones does not split them, which matters because a genuine
    multi-day anomaly often has one hour that scrapes back under the threshold.
    """
    if not flagged:
        return []
    ordered = sorted(flagged)
    windows: list[tuple[datetime, datetime]] = []
    start = prev = ordered[0]
    for current in ordered[1:]:
        if current - prev <= step * (max_gap + 1):
            prev = current
            continue
        windows.append((start, prev + step))
        start = prev = current
    windows.append((start, prev + step))
    return windows


def baseline_series(
    values: dict[datetime, float], bucket: datetime, weeks: int
) -> list[float]:
    """Like-for-like history: the same bucket one, two ... `weeks` weeks earlier.

    Same weekday and same hour-of-day, which is what keeps weekends from firing - Saturday
    traffic runs ~20% below a weekday and a flat mean would alarm every weekend.
    """
    out = []
    for w in range(1, weeks + 1):
        prior = values.get(bucket - timedelta(weeks=w))
        if prior is not None:
            out.append(prior)
    return out


def score_buckets(
    values: dict[datetime, float],
    requests: dict[datetime, int],
    targets: list[datetime],
    weeks: int,
    min_effect: float = MIN_EFFECT,
) -> list[Bucket]:
    """Score each target bucket against its own like-for-like baseline.

    `min_effect` is a scan-level significance floor on top of the shared detection rule. It
    answers a different question from `baseline._detected` ("is this bucket statistically
    unusual?") - namely "is this incident worth putting in front of a human?".

    It is load-bearing here for a reason specific to merging. With baseline_weeks=3 the MAD is
    computed over three points and collapses toward zero, so a 0.0% move can still score z=8.6.
    Those buckets are individually harmless, but they bridge the gaps between genuine anomalies
    and merge Jun 23-25 and Jun 28-30 into one meaningless ten-day window. Filtering before the
    merge is what keeps distinct incidents distinct.

    See JAL-74, which tightens `_detected` itself; the two are aligned at 5%.
    """
    scored = []
    for bucket in sorted(targets):
        observed = values.get(bucket)
        series = baseline_series(values, bucket, weeks)
        if observed is None or not series:
            continue
        centre = med(series)
        spread = mad(series, centre)
        z = robust_z(observed, centre, spread)
        pct = pct_delta(observed, centre)
        scored.append(
            Bucket(
                bucket=bucket, observed=observed, expected=centre, robust_z=z, pct_delta=pct,
                requests=requests.get(bucket, 0),
                detected=_detected(z, spread, pct) and abs(pct) >= min_effect,
            )
        )
    return scored


def build_incidents(metric: str, scored: list[Bucket], step: timedelta) -> list[Incident]:
    """Group detected buckets into incidents, ranked by severity weighted by volume.

    Volume weighting matters: a 40% swing on a bucket with 12 requests is noise, while the
    same swing across a full day of traffic is the thing you want at the top of the list.
    """
    incidents = []
    for start, end in merge_windows([b.bucket for b in scored if b.detected], step):
        # Include every bucket in the window, not just the flagged ones, so a short
        # recovery inside an incident still counts toward its volume.
        members = [b for b in scored if start <= b.bucket < end]
        peak = max(members, key=lambda b: abs(b.robust_z))
        volume = sum(b.requests for b in members)
        incidents.append(
            Incident(
                metric=metric, window_start=start, window_end=end,
                direction="drop" if peak.observed < peak.expected else "spike",
                peak_z=peak.robust_z, peak_pct_delta=peak.pct_delta,
                observed=peak.observed, expected=peak.expected,
                affected_requests=volume, buckets=len(members),
                score=abs(peak.pct_delta) * volume,
            )
        )
    return incidents


# ---- engine (runs against ClickHouse) --------------------------------------

def _series_sql(metric: str, grain: str) -> str:
    """One pass covering the target range AND its trailing history."""
    # `AS bucket_requests`, not `AS requests`: aliasing to the column name makes ClickHouse
    # resolve the inner `requests` to the alias and reject it as a nested aggregate.
    return (
        f"SELECT {_GRAIN_SQL[grain]} AS bucket, {metric_sql(metric, 'rollup')} AS value, "
        f"sum(requests) AS bucket_requests FROM {_HOURLY} "
        f"WHERE hour >= toDateTime({{hist_start:String}}) AND hour < toDateTime({{end:String}}) "
        f"GROUP BY bucket ORDER BY bucket"
    )


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def scan_incidents(
    start: datetime,
    end: datetime,
    metrics: list[str] | None = None,
    grain: str | None = None,
    min_effect: float = MIN_EFFECT,
) -> ScanResult:
    """Sweep [start, end) across every metric and return ranked, merged incidents."""
    grain = grain or "day"
    if grain not in _GRAIN_SQL:
        raise ValueError(f"grain must be one of {sorted(_GRAIN_SQL)}, got {grain!r}")
    metrics = metrics or DEFAULT_METRICS
    weeks = _DET["baseline_weeks"]
    step = _GRAIN_STEP[grain]
    hist_start = start - timedelta(weeks=weeks)

    incidents: list[Incident] = []
    queries: list[dict] = []
    for metric in metrics:
        out = run_query(
            _series_sql(metric, grain),
            {"hist_start": _fmt(hist_start), "end": _fmt(end)},
            name=f"scan:{metric}",
        )
        values = {r[0]: float(r[1]) for r in out["rows"] if r[1] is not None}
        requests = {r[0]: int(r[2]) for r in out["rows"]}
        targets = [b for b in values if start <= b < end]
        scored = score_buckets(values, requests, targets, weeks, min_effect)
        found = build_incidents(metric, scored, step)
        incidents.extend(found)
        queries.append({
            "id": f"q_scan_{metric}",
            "sql": out["resolved_sql"],
            "result_summary": {"buckets": len(targets), "incidents": len(found)},
            "langfuse_span_id": out.get("langfuse_span_id"),
        })

    incidents.sort(key=lambda i: i.score, reverse=True)
    return ScanResult(incidents=incidents, queries=queries)
