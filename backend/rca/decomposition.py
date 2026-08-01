"""Lane B: factor decomposition via the revenue identity.

Revenue ~= Requests x FillRate x eCPM/1000. Attribute the total delta across factors
(log-additive). Whichever carries most of the delta is primary_factor; flat ones -> ruled_out.
"""
from __future__ import annotations

from models import FactorDecomposition, Window


def decompose(metric: str, target: Window, baseline: Window) -> tuple[FactorDecomposition, list[dict]]:
    # TODO(Lane B): pull requests/fill_rate/ecpm for target vs baseline, log-additive attribution.
    raise NotImplementedError("Lane B: implement decompose — see prompts/02-detection-rca.md")
