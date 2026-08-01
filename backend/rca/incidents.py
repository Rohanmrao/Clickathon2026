from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config import config
from data.calibration import effect_threshold
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
    calibrated_effect: float,
    min_effect: float = MIN_EFFECT,
) -> list[Bucket]:
    """Score each target bucket against its own like-for-like baseline.

    `calibrated_effect` is `_detected`'s per-metric, auto-calibrated effect-size floor (see
    data.calibration.effect_threshold) — computed by the CALLER (scan_incidents, which already
    talks to ClickHouse per metric) and passed in as a plain number, deliberately, so this
    function stays DB-free and unit-testable (see tests/test_incidents.py).

    `min_effect` is a SEPARATE, additional scan-level significance floor on top of that. It
    answers a different question from `_detected` ("is this bucket statistically unusual, by
    a real amount?") - namely "is this incident worth putting in front of a human?".

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
        z = robust_z(observed, centre, spread, _DET["mad_scale"])
        pct = pct_delta(observed, centre)
        scored.append(
            Bucket(
                bucket=bucket, observed=observed, expected=centre, robust_z=z, pct_delta=pct,
                requests=requests.get(bucket, 0),
                detected=_detected(z, spread, pct, calibrated_effect) and abs(pct) >= min_effect,
                # ^ calibrated_effect is a plain number (see docstring); no metric/DB lookup here.
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
        calibrated_effect = effect_threshold(metric)  # DB-touching; belongs in this loop, not score_buckets
        scored = score_buckets(values, requests, targets, weeks, calibrated_effect, min_effect)
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


# ---- per-segment scan: catches anomalies scan_incidents structurally cannot see -----------
#
# scan_incidents() only ever checks the GLOBAL aggregate per metric. That misses anything
# localized to one segment whose effect gets diluted below the detection floor once averaged
# across every other (unaffected, or growing) segment. Confirmed on real data: APAC fill_rate
# collapsed ~6-7% (z in the hundreds) on Jun 28-30, while the GLOBAL fill_rate move that same
# window was only 0.8-2.3% - comfortably under the calibrated floor - because total traffic
# was simultaneously growing (organic volume growth masked a real regional problem). Global-only
# scanning would never surface this; it was only found because a code comment happened to
# mention it. This function exists so "how many anomalies are in this dataset" doesn't depend
# on stumbling across a hint.

# Low-cardinality dimensions only for a broad sweep. app_id (2000 values) and advertiser_id
# (501) are excluded here deliberately: at ~2 requests/hour/app, ratio metrics degenerate
# (fill_rate can only be 0, 0.5, or 1 - see project-clickathon-detection-methodology memory),
# so a broad per-app sweep would mostly surface sampling-noise artifacts, not real incidents.
SEGMENT_SCAN_DIMENSIONS = [
    "region", "country", "os_version", "device_model", "ad_format",
    "category", "publisher_tier", "vertical", "campaign_type",
]

# Below this many requests over the WHOLE scan window, a segment's ratio metrics are too
# sparse to trust (same degenerate-ratio problem as app_id, just for any segment that happens
# to be small). Filters noise without hardcoding which segments to skip.
MIN_SEGMENT_VOLUME = 5_000


def _series_sql_by_segment(metric: str, grain: str, dimension: str) -> str:
    """One pass covering every value of `dimension` at once - vectorized (one query
    regardless of cardinality), not one query per segment value. See the ~5000x benchmark
    in project-clickathon-detection-methodology memory for why this matters."""
    return (
        f"SELECT {dimension} AS seg, {_GRAIN_SQL[grain]} AS bucket, "
        f"{metric_sql(metric, 'rollup')} AS value, sum(requests) AS bucket_requests "
        f"FROM {_HOURLY} "
        f"WHERE hour >= toDateTime({{hist_start:String}}) AND hour < toDateTime({{end:String}}) "
        f"GROUP BY seg, bucket ORDER BY seg, bucket"
    )


def scan_segments(
    start: datetime,
    end: datetime,
    metrics: list[str] | None = None,
    dimensions: list[str] | None = None,
    grain: str | None = None,
    min_effect: float = MIN_EFFECT,
    min_segment_volume: int = MIN_SEGMENT_VOLUME,
) -> ScanResult:
    """Sweep [start, end) across every metric AND every value of every dimension.

    One query per (metric, dimension) pair fetches every segment value's series at once
    (vectorized SQL), then the same pure score_buckets()/build_incidents() logic used by
    scan_incidents() runs once per segment in Python - no DB access in that inner loop, so
    looping there is cheap even at high cardinality.

    Incident IDs are namespaced as "metric[dimension=value]" so they're distinguishable from
    scan_incidents()'s plain "metric" IDs in a combined result set.
    """
    grain = grain or "day"
    if grain not in _GRAIN_SQL:
        raise ValueError(f"grain must be one of {sorted(_GRAIN_SQL)}, got {grain!r}")
    metrics = metrics or DEFAULT_METRICS
    dimensions = dimensions or SEGMENT_SCAN_DIMENSIONS
    weeks = _DET["baseline_weeks"]
    step = _GRAIN_STEP[grain]
    hist_start = start - timedelta(weeks=weeks)

    incidents: list[Incident] = []
    queries: list[dict] = []
    for metric in metrics:
        calibrated_effect = effect_threshold(metric)
        for dimension in dimensions:
            out = run_query(
                _series_sql_by_segment(metric, grain, dimension),
                {"hist_start": _fmt(hist_start), "end": _fmt(end)},
                name=f"scan_seg:{metric}:{dimension}",
            )
            by_seg_values: dict[str, dict[datetime, float]] = {}
            by_seg_requests: dict[str, dict[datetime, int]] = {}
            for seg, bucket, value, bucket_requests in out["rows"]:
                if not seg or value is None:  # skip empty-string segments (e.g. unfilled rows)
                    continue
                by_seg_values.setdefault(seg, {})[bucket] = float(value)
                by_seg_requests.setdefault(seg, {})[bucket] = int(bucket_requests)

            found_this_pass = 0
            for seg, values in by_seg_values.items():
                if sum(by_seg_requests[seg].values()) < min_segment_volume:
                    continue
                targets = [b for b in values if start <= b < end]
                scored = score_buckets(values, by_seg_requests[seg], targets, weeks, calibrated_effect, min_effect)
                found = build_incidents(f"{metric}[{dimension}={seg}]", scored, step)
                incidents.extend(found)
                found_this_pass += len(found)

            queries.append({
                "id": f"q_scan_seg_{metric}_{dimension}",
                "sql": out["resolved_sql"],
                "result_summary": {"segments": len(by_seg_values), "incidents": found_this_pass},
                "langfuse_span_id": out.get("langfuse_span_id"),
            })

    incidents.sort(key=lambda i: i.score, reverse=True)
    return ScanResult(incidents=incidents, queries=queries)
