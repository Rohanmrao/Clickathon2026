"""Lane B: detection dispatcher.

Selects a detector strategy from config.detection.method and delegates. Every detector returns the
identical (Anomaly, queries) contract, so everything downstream is agnostic to which one ran.

  * robust_z    — deterministic like-for-like baseline (median/MAD over trailing weeks). Default.
  * seasonal_ml — unsupervised seasonal-residual model over all history.
"""
from __future__ import annotations

from collections.abc import Callable

from config import config
from models import Anomaly, Window
from rca.detectors import robust_z, seasonal_ml

Runner = Callable[[str, Window], "tuple[Anomaly, list[dict]]"]

_DETECTORS: dict[str, Runner] = {
    "robust_z": robust_z.run,
    "seasonal_ml": seasonal_ml.run,
}


def _select(method: str) -> Runner:
    try:
        return _DETECTORS[method]
    except KeyError:
        raise ValueError(f"unknown detection method: {method!r} (known: {sorted(_DETECTORS)})")


def detect(metric: str, target: Window) -> tuple[Anomaly, list[dict]]:
    """Return (Anomaly, queries) for `metric` at `target`, via the configured detector."""
    return _select(config()["detection"]["method"])(metric, target)
