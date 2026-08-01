"""JAL-78: incident scanning logic, exercised without a database.

The behaviour that actually matters here is window merging. A 3-day anomaly at hourly grain
fires ~72 separate alerts; without merging, the system produces 72 near-identical
investigations of one event.
"""
from datetime import datetime, timedelta

import pytest

from rca import incidents as inc

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)
D = lambda n: datetime(2026, 6, n)  # noqa: E731 - terse date literal for tables of cases


# ---- merge_windows ---------------------------------------------------------

def test_no_flags_gives_no_windows():
    assert inc.merge_windows([], DAY) == []


def test_single_flag_becomes_one_window():
    assert inc.merge_windows([D(23)], DAY) == [(D(23), D(24))]


def test_contiguous_days_collapse_into_one_window():
    """Anomaly A spans Jun 23-25 and must surface as ONE incident, not three."""
    assert inc.merge_windows([D(23), D(24), D(25)], DAY) == [(D(23), D(26))]


def test_separated_flags_stay_separate():
    """Jun 21 and Jun 28-30 are different incidents and must not be glued together."""
    assert inc.merge_windows([D(21), D(28), D(29), D(30)], DAY) == [
        (D(21), D(22)),
        (D(28), datetime(2026, 7, 1)),  # exclusive end rolls into July
    ]


def test_one_clean_bucket_does_not_split_an_incident():
    """A single bucket scraping back under threshold mid-anomaly is still one incident."""
    assert inc.merge_windows([D(23), D(25)], DAY, max_gap=1) == [(D(23), D(26))]


def test_two_clean_buckets_do_split():
    assert inc.merge_windows([D(23), D(26)], DAY, max_gap=1) == [(D(23), D(24)), (D(26), D(27))]


def test_unsorted_input_is_handled():
    assert inc.merge_windows([D(25), D(23), D(24)], DAY) == [(D(23), D(26))]


def test_hourly_grain_merges_a_long_run():
    """72 hourly alerts over 3 days must collapse to a single window."""
    base = datetime(2026, 6, 23)
    flagged = [base + HOUR * i for i in range(72)]

    merged = inc.merge_windows(flagged, HOUR)

    assert merged == [(base, base + HOUR * 72)]


# ---- baseline_series -------------------------------------------------------

def test_baseline_series_takes_same_weekday_prior_weeks():
    values = {D(23): 0.43, D(16): 0.785, D(9): 0.786, D(2): 0.784}

    assert inc.baseline_series(values, D(23), weeks=3) == [0.785, 0.786, 0.784]


def test_baseline_series_skips_missing_history():
    values = {D(23): 0.43, D(16): 0.785}

    assert inc.baseline_series(values, D(23), weeks=3) == [0.785]


def test_baseline_series_empty_when_no_history():
    assert inc.baseline_series({D(2): 0.78}, D(2), weeks=3) == []


# ---- score_buckets ---------------------------------------------------------

def _fill_rate_history(target_value):
    """Three clean weeks of ~0.785 fill rate, then the target bucket."""
    return {D(2): 0.784, D(9): 0.786, D(16): 0.785, D(23): target_value}


# 0.03 mirrors the real calibrated fill_rate floor measured in data/calibration.py testing
# (docs/TEST_CASES.md) — a plain number here since score_buckets is DB-free by design.
_FILL_RATE_EFFECT = 0.03


def test_bucket_with_no_history_is_skipped_not_crashed():
    scored = inc.score_buckets({D(2): 0.78}, {D(2): 100}, [D(2)], weeks=3, calibrated_effect=_FILL_RATE_EFFECT)

    assert scored == []


def test_scored_bucket_carries_direction_inputs():
    values = _fill_rate_history(0.428)
    scored = inc.score_buckets(values, {D(23): 27370}, [D(23)], weeks=3, calibrated_effect=_FILL_RATE_EFFECT)

    assert len(scored) == 1
    bucket = scored[0]
    assert bucket.observed == 0.428
    assert bucket.expected == pytest.approx(0.785, abs=1e-3)
    assert bucket.pct_delta < -0.4
    assert bucket.requests == 27370


def test_flat_series_is_not_flagged():
    values = {D(2): 0.784, D(9): 0.786, D(16): 0.785, D(23): 0.7851}
    scored = inc.score_buckets(values, {D(23): 27000}, [D(23)], weeks=3, calibrated_effect=_FILL_RATE_EFFECT)

    assert scored[0].detected is False


# ---- build_incidents -------------------------------------------------------

def _bucket(day, *, z, pct, requests, detected):
    return inc.Bucket(bucket=D(day), observed=0.43, expected=0.785, robust_z=z,
                      pct_delta=pct, requests=requests, detected=detected)


def test_build_incidents_groups_a_run():
    scored = [
        _bucket(23, z=-120.0, pct=-0.45, requests=27000, detected=True),
        _bucket(24, z=-136.0, pct=-0.46, requests=26800, detected=True),
        _bucket(25, z=-118.0, pct=-0.44, requests=26500, detected=True),
    ]

    got = inc.build_incidents("fill_rate", scored, DAY)

    assert len(got) == 1
    assert (got[0].window_start, got[0].window_end) == (D(23), D(26))
    assert got[0].buckets == 3
    assert got[0].peak_z == -136.0            # worst bucket, not the first
    assert got[0].affected_requests == 80300  # summed across the window
    assert got[0].direction == "drop"


def test_undetected_buckets_produce_no_incident():
    scored = [_bucket(23, z=-1.0, pct=-0.01, requests=27000, detected=False)]

    assert inc.build_incidents("fill_rate", scored, DAY) == []


def test_spike_direction_is_detected():
    b = inc.Bucket(bucket=D(23), observed=0.9, expected=0.785, robust_z=40.0,
                   pct_delta=0.146, requests=27000, detected=True)

    assert inc.build_incidents("ecpm", [b], DAY)[0].direction == "spike"


def test_incident_id_is_stable_and_readable():
    b = _bucket(23, z=-136.0, pct=-0.46, requests=27000, detected=True)

    got = inc.build_incidents("fill_rate", [b], DAY)[0]

    assert got.incident_id() == "fill_rate:2026-06-23T00"
    assert inc.build_incidents("fill_rate", [b], DAY)[0].incident_id() == got.incident_id()


def test_score_weights_severity_by_volume():
    """A big swing on tiny volume must rank below a smaller swing on real traffic."""
    tiny = _bucket(23, z=-50.0, pct=-0.90, requests=12, detected=True)
    real = _bucket(25, z=-20.0, pct=-0.30, requests=250_000, detected=True)

    got = inc.build_incidents("fill_rate", [tiny], DAY) + inc.build_incidents("fill_rate", [real], DAY)
    got.sort(key=lambda i: i.score, reverse=True)

    assert got[0].window_start == D(25)


def test_scan_rejects_unknown_grain():
    with pytest.raises(ValueError, match="grain"):
        inc.scan_incidents(D(1), D(5), grain="fortnight")
