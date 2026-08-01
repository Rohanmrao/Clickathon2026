"""Central config + env access. No magic strings elsewhere — read from here."""
import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@lru_cache
def config() -> dict:
    return json.loads(_CONFIG_PATH.read_text())


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


CLICKHOUSE = {
    "host": env("CLICKHOUSE_HOST"),
    "port": int(env("CLICKHOUSE_PORT", "8443")),
    "username": env("CLICKHOUSE_USER", "default"),
    "password": env("CLICKHOUSE_PASSWORD"),
    "database": env("CLICKHOUSE_DATABASE", "default"),
}

LANGFUSE = {
    "public_key": env("LANGFUSE_PUBLIC_KEY"),
    "secret_key": env("LANGFUSE_SECRET_KEY"),
    # SDK ingestion host. In Docker this is the internal service (langfuse-web:3000).
    "host": env("LANGFUSE_HOST", "http://localhost:3000"),
    # Browser-facing base for trace LINKS. The SDK bakes `host` into get_trace_url(), but a
    # container-internal host (langfuse-web:3000) can't be opened from the host browser — so
    # trace URLs are rewritten to this. Defaults to `host` (correct for a host venv run).
    "public_host": env("LANGFUSE_PUBLIC_HOST") or env("LANGFUSE_HOST", "http://localhost:3000"),
}

# AWS Bedrock — auth comes from the standard AWS credential chain (aws cli / env / role),
# so no key is stored here. Region + model default to config.json; env can override.
BEDROCK = {
    "region": env("AWS_REGION") or config()["bedrock"]["region"],
    "model_id": env("BEDROCK_MODEL_ID") or config()["bedrock"]["model_id"],
}
