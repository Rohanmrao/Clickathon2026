"""Lane B: detection. Like-for-like baseline (same weekday+hour, median/MAD over trailing weeks)."""
from __future__ import annotations

from config import config
from models import Anomaly, Window


def detect(metric: str, target: Window) -> tuple[Anomaly, list[dict]]:
    """Return (Anomaly, queries) for `metric` over `target`.

    Baseline = same weekday + hour-of-day, robust (median/MAD) over trailing N weeks.
    Threshold from config.detection.mad_z_threshold. Weekends must NOT fire; the planted
    pure-seasonality decoy must end up ruled out, not alarmed.
    """
    cfg = config()["detection"]  # noqa: F841  (grain, baseline_weeks, mad_z_threshold)
    # TODO(Lane B): compute baseline via data.client.run_query against hourly_summary,
    #   return the Anomaly and the list of {id, sql, result_summary} queries used.
    raise NotImplementedError("Lane B: implement detect — see prompts/02-detection-rca.md")
