"""Lane C: turn an EvidenceBundle into prose. LLM narrates; it never computes.

Feed the bundle, ask for <= config.narrator.max_sentences sentences covering: the headline move,
the localized segment, the responsible factor, and the ruled-out list. Then run the guardrail.
"""
from __future__ import annotations

from config import config
from models import EvidenceBundle
from narrator.guardrail import verify

SYSTEM = (
    "You are a data analyst writing a diagnosis. Use ONLY numbers present in the provided "
    "evidence bundle. Never compute, infer, or round into a new figure. State the headline move, "
    "the localized segment, the responsible factor, and what was checked and ruled out."
)


def narrate(bundle: EvidenceBundle) -> EvidenceBundle:
    cfg = config()["narrator"]  # noqa: F841  (max_sentences, temperature)
    # TODO(Lane C): call the LLM with SYSTEM + bundle JSON; on guardrail failure, re-prompt or strip.
    prose = _call_llm(bundle)
    bundle.narrative = prose
    bundle.narrative_verification = verify(bundle, prose)
    return bundle


def _call_llm(bundle: EvidenceBundle) -> str:
    raise NotImplementedError("Lane C: implement _call_llm — see prompts/03-narrator-orchestration.md")
