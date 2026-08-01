"""Lane C: hallucination guardrail. Every number in the prose must exist in the bundle.

This is pure logic (no deps) so it works today. It is the trustworthiness backstop:
a single fabricated figure costs more than a missed anomaly.
"""
from __future__ import annotations

import re

from models import EvidenceBundle, NarrativeVerification

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _numbers(text: str) -> set[str]:
    return {_norm(m) for m in _NUM.findall(text or "")}


def _norm(token: str) -> str:
    return token.replace(",", "").rstrip(".").lstrip("-")


def _bundle_numbers(bundle: EvidenceBundle) -> set[str]:
    # Collect every numeric token that appears anywhere in the evidence.
    haystack = bundle.model_dump_json(exclude={"narrative", "narrative_verification"})
    tokens = {_norm(m) for m in _NUM.findall(haystack)}
    # Also allow the % form of any fraction (e.g. -0.152 -> 15.2) plus rounded variants.
    for t in list(tokens):
        try:
            f = float(t)
        except ValueError:
            continue
        tokens.add(_norm(f"{abs(f) * 100:.2f}"))  # 2dp % (Sonnet's default, e.g. -0.0332 -> 3.32)
        tokens.add(_norm(f"{abs(f) * 100:.1f}"))
        tokens.add(_norm(f"{abs(f) * 100:.0f}"))
        tokens.add(_norm(f"{f:.0f}"))
    return tokens


def verify(bundle: EvidenceBundle, narrative: str) -> NarrativeVerification:
    allowed = _bundle_numbers(bundle)
    unverified = sorted(n for n in _numbers(narrative) if n and n not in allowed)
    return NarrativeVerification(passed=not unverified, unverified_numbers=unverified)
