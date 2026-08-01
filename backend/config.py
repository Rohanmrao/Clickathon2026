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
    "host": env("LANGFUSE_HOST", "https://cloud.langfuse.com"),
}

LLM = {"api_key": env("LLM_API_KEY"), "model": env("LLM_MODEL")}
