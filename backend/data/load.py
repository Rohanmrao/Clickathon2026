"""Lane A: load the four InMobi files into ClickHouse, then build enriched + rollup tables.

    python -m data.load

Idempotent: truncates raw tables and rebuilds derived tables, so re-runs give a clean state.
Uses clickhouse-connect's insert_file (server-side parsing) — no pyarrow needed.
"""
from __future__ import annotations

import re
from pathlib import Path

from clickhouse_connect.driver.tools import insert_file

from config import config
from data.client import get_client

DATA_DIR = Path(__file__).resolve().parents[2] / "InMobi" / "data"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"
DERIVED = Path(__file__).resolve().parent / "derived.sql"

_CH = config()["clickhouse"]
RAW_TABLES = ["ad_events", "apps", "advertisers", "geo_device"]
DERIVED_TABLES = [_CH["enriched_table"], _CH["hourly_table"]]

CSV_FILES = {"apps": "apps.csv", "advertisers": "advertisers.csv", "geo_device": "geo_device.csv"}


def _run_sql_file(client, path: Path) -> None:
    no_comments = "\n".join(re.sub(r"--.*$", "", ln) for ln in path.read_text().splitlines())
    for chunk in no_comments.split(";"):
        stmt = chunk.strip()
        if stmt:
            client.command(stmt)


def main() -> None:
    client = get_client()

    print("1/5  create raw tables")
    _run_sql_file(client, SCHEMA)

    print("2/5  truncate raw tables (clean re-run)")
    for t in RAW_TABLES:
        client.command(f"TRUNCATE TABLE {t}")

    print("3/5  load dimension CSVs")
    for table, fname in CSV_FILES.items():
        insert_file(client, table, str(DATA_DIR / fname), fmt="CSVWithNames")
        print(f"       {table}: {client.query(f'SELECT count() FROM {table}').result_rows[0][0]:,}")

    print("4/5  load ad_events.parquet (9M rows, ~99MB — this is the slow step)")
    insert_file(client, "ad_events", str(DATA_DIR / "ad_events.parquet"), fmt="Parquet")

    print("5/5  build derived tables (events_enriched, metrics_hourly)")
    for t in DERIVED_TABLES:
        client.command(f"DROP TABLE IF EXISTS {t}")
    _run_sql_file(client, DERIVED)

    _verify(client)


def _verify(client) -> None:
    print("\n--- verification ---")
    events = client.query("SELECT count() FROM ad_events").result_rows[0][0]
    enriched = client.query(f"SELECT count() FROM {_CH['enriched_table']}").result_rows[0][0]
    hourly = client.query(f"SELECT count() FROM {_CH['hourly_table']}").result_rows[0][0]
    span = client.query("SELECT min(event_time), max(event_time) FROM ad_events").result_rows[0]
    regions = client.query("SELECT groupUniqArray(region) FROM geo_device").result_rows[0][0]
    print(f"ad_events       : {events:,}")
    print(f"events_enriched : {enriched:,}")
    print(f"metrics_hourly  : {hourly:,} rows")
    print(f"date range      : {span[0]} -> {span[1]}")
    print(f"regions         : {regions}  (expect NAM present, not NA)")
    assert events == enriched, "enriched row count must equal ad_events"


if __name__ == "__main__":
    main()
