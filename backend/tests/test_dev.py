"""/dev admin dashboard — endpoint logic with the DB patched (no live ClickHouse)."""
import copy
from unittest.mock import patch

import pytest

from api import dev
from config import config
from models import Anomaly


def _fake_run_query(count=42):
    def fn(sql, params=None):
        s = sql.strip()
        if s == "SHOW TABLES":
            return {"rows": [["ad_events"], ["hourly_summary"]], "columns": ["name"]}
        if s.startswith("SELECT count()"):
            return {"rows": [[count]], "columns": ["count()"]}
        if s.startswith("SELECT *"):
            return {"rows": [[1, 2]], "columns": ["a", "b"], "resolved_sql": s}
        raise AssertionError(f"unexpected sql: {sql}")
    return fn


def test_list_tables_returns_names_and_counts():
    with patch.object(dev, "run_query", _fake_run_query(9)):
        out = dev.list_tables()
    assert out == [{"name": "ad_events", "rows": 9}, {"name": "hourly_summary", "rows": 9}]


def test_preview_rejects_unknown_table():
    with patch.object(dev, "run_query", _fake_run_query()):
        with pytest.raises(ValueError):
            dev.preview_table("bobby_drop", limit=5)


def test_preview_returns_columns_and_rows():
    with patch.object(dev, "run_query", _fake_run_query()):
        out = dev.preview_table("ad_events", limit=5)
    assert out["columns"] == ["a", "b"]
    assert out["rows"] == [[1, 2]]


def test_drop_requires_matching_confirm():
    with patch.object(dev, "run_query", _fake_run_query()):
        with pytest.raises(ValueError):
            dev.drop_table("ad_events", confirm="wrong")


def test_drop_executes_on_matching_confirm():
    calls = {}

    class FakeClient:
        def command(self, sql, parameters=None):
            calls["sql"] = sql

    with patch.object(dev, "run_query", _fake_run_query()), patch.object(dev, "get_client", lambda: FakeClient()):
        out = dev.drop_table("ad_events", confirm="ad_events")
    assert out == {"dropped": "ad_events"}
    assert "DROP TABLE" in calls["sql"]


def test_detect_applies_override_then_restores_config():
    seen = {}

    def fake_detect(metric, window):
        seen["method"] = config()["detection"]["method"]
        seen["thr"] = config()["detection"]["mad_z_threshold"]
        return Anomaly(detected=True, observed=1, expected=1, abs_delta=0, pct_delta=0, score=0, direction="spike"), []

    before = copy.deepcopy(config()["detection"])
    with patch.object(dev, "detect", fake_detect):
        out = dev.run_detect("revenue", "2026-07-04T10:00", method="seasonal_ml", overrides={"mad_z_threshold": 9.9})
    assert seen["method"] == "seasonal_ml"          # override active during the run
    assert seen["thr"] == 9.9
    assert config()["detection"] == before          # ...and fully restored afterward
    assert out["anomaly"]["detected"] is True


def test_detect_deep_merges_nested_override_and_restores():
    seen = {}

    def fake_detect(metric, window):
        d = config()["detection"]["isolation_forest"]
        seen["features"] = d["features"]
        seen["n_estimators"] = d["n_estimators"]  # sibling key must survive the nested override
        return Anomaly(detected=False, observed=1, expected=1, abs_delta=0, pct_delta=0, score=0, direction="spike"), []

    before = copy.deepcopy(config()["detection"])
    with patch.object(dev, "detect", fake_detect):
        dev.run_detect("revenue", "2026-07-04T10:00", method="isolation_forest",
                       overrides={"isolation_forest": {"features": "multivariate"}})
    assert seen["features"] == "multivariate"    # nested override applied
    assert seen["n_estimators"] == 200           # ...without clobbering siblings (deep merge)
    assert config()["detection"] == before       # fully restored


def test_benchmark_cases_returns_the_four_ground_truth_cases():
    cases = dev.benchmark_cases()
    assert {c["id"] for c in cases} == {"A", "B", "C", "D"}


def test_dev_enabled_default_on_and_off(monkeypatch):
    monkeypatch.delenv("ENABLE_DEV_DASHBOARD", raising=False)
    assert dev.dev_enabled() is True
    monkeypatch.setenv("ENABLE_DEV_DASHBOARD", "0")
    assert dev.dev_enabled() is False
