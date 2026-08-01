"""Lane C: turn an EvidenceBundle into prose. LLM narrates; it never computes.

Feed the bundle, ask for <= config.narrator.max_sentences sentences covering: the headline move,
the localized segment, the responsible factor, and the ruled-out list. Then run the guardrail.
"""
from __future__ import annotations

import boto3

from config import BEDROCK, config
from models import EvidenceBundle
from narrator.guardrail import verify

SYSTEM = (
    "You are a data analyst writing a diagnosis. Use ONLY numbers present in the provided "
    "evidence bundle. Never compute, infer, or round into a new figure. State the headline move, "
    "the localized segment, the responsible factor, and what was checked and ruled out."
)

# Only the evidence fields the narrator may draw from — keeps the prompt tight.
_EVIDENCE = {"metric", "anomaly", "factor_decomposition", "drilldown", "localized_segment", "ruled_out"}


def narrate(bundle: EvidenceBundle) -> EvidenceBundle:
    # TODO(Lane C): on guardrail failure, re-prompt or strip the offending number.
    prose = _call_llm(bundle)
    bundle.narrative = prose
    bundle.narrative_verification = verify(bundle, prose)
    return bundle


def _call_llm(bundle: EvidenceBundle) -> str:
    cfg = config()["narrator"]
    client = boto3.client("bedrock-runtime", region_name=BEDROCK["region"])
    prompt = (
        f"{SYSTEM}\n\nWrite at most {cfg['max_sentences']} sentences.\n\n"
        f"Evidence bundle (JSON):\n{bundle.model_dump_json(include=_EVIDENCE)}"
    )
    resp = client.converse(
        modelId=BEDROCK["model_id"],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 400, "temperature": cfg["temperature"]},
    )
    return resp["output"]["message"]["content"][0]["text"].strip()
