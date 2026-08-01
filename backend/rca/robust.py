"""Robust statistics primitives for like-for-like baselines. Pure, dependency-free, unit-tested."""
from __future__ import annotations

from statistics import median

_MAD_SCALE = 1.4826  # scales MAD to be comparable to std-dev on normally distributed data


def med(values: list[float]) -> float:
    return float(median(values)) if values else 0.0


def mad(values: list[float], center: float | None = None) -> float:
    """Median absolute deviation."""
    if not values:
        return 0.0
    c = med(values) if center is None else center
    return float(median([abs(v - c) for v in values]))


def robust_z(value: float, center: float, mad_value: float) -> float:
    """MAD-based z-score. Returns 0.0 on degenerate spread — caller applies a pct fallback."""
    denom = mad_value * _MAD_SCALE
    return (value - center) / denom if denom else 0.0


def pct_delta(observed: float, expected: float) -> float:
    return (observed - expected) / expected if expected else 0.0
