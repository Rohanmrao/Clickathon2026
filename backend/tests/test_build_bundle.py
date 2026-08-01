"""JAL-37/36/38: build_bundle assembles a schema-valid EvidenceBundle end to end."""
import json
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest

from models import Factor, FactorDecomposition, Window
from rca import bundle

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts" / "evidence_bundle.schema.json").read_text())

try:
    from data.client import run_query
    run_query("SELECT 1")
    _DB_UP = True
except Exception:  # noqa: BLE001
    _DB_UP = False


# ---- pure: ruled_out from flat, non-primary factors (JAL-31/36) ------------

def test_ruled_out_flags_flat_non_primary_factors():
    fd = FactorDecomposition(primary_factor="requests", factors=[
        Factor(factor="requests", contribution_pct=0.96, from_=220000, to=126000),
        Factor(factor="fill_rate", contribution_pct=-0.002, from_=0.785, to=0.7855),
        Factor(factor="ecpm", contribution_pct=0.042, from_=2.48, to=2.42),
    ])
    ruled = bundle._ruled_out(fd, "q_decompose")
    assert {r.hypothesis for r in ruled} == {"fill_rate", "ecpm_price"}   # primary (requests) excluded
    assert all(r.query_id == "q_decompose" for r in ruled)
    assert all(r.evidence for r in ruled)


# ---- live end-to-end -------------------------------------------------------

pytestmark = pytest.mark.skipif(not _DB_UP, reason="needs live ClickHouse")


def test_case_a_bundle_localizes_and_validates_schema():
    window = Window(start=datetime(2026, 6, 23), end=datetime(2026, 6, 26))
    b = bundle.build_bundle("fill_rate", window)
    jsonschema.validate(b.model_dump(mode="json", by_alias=True, exclude_none=True), SCHEMA)   # JAL-38
    assert b.localized_segment == {"os_version": "Android 15"}              # drill localizes the culprit
    qids = {q.id for q in b.queries}
    assert all(node.query_id in qids for node in b.drilldown)               # every node traces to a query


def test_revenue_bundle_detects_and_names_primary_factor():
    window = Window(start=datetime(2026, 6, 21), end=datetime(2026, 6, 22))
    b = bundle.build_bundle("revenue", window)
    jsonschema.validate(b.model_dump(mode="json", by_alias=True, exclude_none=True), SCHEMA)
    assert b.anomaly.detected is True                     # revenue collapsed on Jun 21
    assert b.factor_decomposition.primary_factor == "requests"
