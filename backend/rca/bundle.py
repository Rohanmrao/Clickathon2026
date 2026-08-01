"""Lane B: assemble a schema-valid EvidenceBundle from detection + decomposition + drill-down.

This is the object the whole system flows through. Every number in it must trace to a query
in `queries`. narrative / trace_url are filled later by Lane C.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from models import EvidenceBundle, Window
from rca.decomposition import decompose
from rca.detection import detect
from rca.drilldown import drill


def build_bundle(metric: str, target: Window) -> EvidenceBundle:
    anomaly, q_detect = detect(metric, target)
    baseline = _baseline_window(target)
    factors, q_decomp = decompose(metric, target, baseline)
    path, localized, q_drill = drill(metric, factors.primary_factor, target, baseline)

    # TODO(Lane B): assemble ruled_out[] (flat factors + explicit checks) with query_ids.
    return EvidenceBundle(
        investigation_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        metric=metric,
        target_window=target,
        baseline_window=_baseline_descriptor(),
        anomaly=anomaly,
        factor_decomposition=factors,
        drilldown=path,
        localized_segment=localized,
        ruled_out=[],
        queries=[*q_detect, *q_decomp, *q_drill],
    )


def _baseline_window(target: Window) -> Window:
    # TODO(Lane B): derive the trailing same-weekday/hour comparison window.
    raise NotImplementedError


def _baseline_descriptor():
    from models import BaselineWindow

    return BaselineWindow(
        method="same_weekday_trailing_weeks",
        description="same weekday + hour-of-day, median over trailing 3 weeks",
        weeks=3,
    )
