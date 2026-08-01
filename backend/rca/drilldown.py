"""Lane B: recursive contribution drill-down.

For the responsible factor, rank dimension values by contribution to the total delta
(delta_segment / delta_total), take the top, add to the cumulative filter, recurse.
Stop when marginal contribution < config.rca.stop_contribution_threshold or max_depth hit.
Build the drill-down GENERICALLY over config.rca.drilldown_dimensions — never hardcode a segment.
"""
from __future__ import annotations

from config import config
from models import DrilldownNode, Window


def drill(metric: str, factor: str, target: Window, baseline: Window) -> tuple[list[DrilldownNode], dict, list[dict]]:
    """Return (drilldown_path, localized_segment, queries)."""
    cfg = config()["rca"]  # noqa: F841  (drilldown_dimensions, stop_contribution_threshold, max_depth)
    # TODO(Lane B): implement the recursive ranking. Each visited node -> DrilldownNode(status, query_id).
    raise NotImplementedError("Lane B: implement drill — see prompts/02-detection-rca.md")
