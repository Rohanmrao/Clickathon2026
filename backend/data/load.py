"""Lane A: load the four InMobi files into ClickHouse, then build enriched + rollup tables.

Usage:  python -m data.load
Expects schema.sql tables to be creatable from scratch. See prompts/01-data-clickhouse.md.
"""
from __future__ import annotations

from pathlib import Path

from data.client import get_client

DATA_DIR = Path(__file__).resolve().parents[2] / "InMobi" / "data"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"

CSV_TABLES = {
    "apps": "apps.csv",
    "advertisers": "advertisers.csv",
    "geo_device": "geo_device.csv",
}


def main() -> None:
    client = get_client()
    # TODO(Lane A):
    #   1. Execute the CREATE TABLE statements for the raw fact + dim tables (schema.sql, top section).
    #   2. Insert ad_events.parquet  ->  ad_events   (client.insert_df / INSERT FROM INFILE).
    #   3. Insert the three CSVs      ->  dim tables  (see CSV_TABLES).
    #   4. Build events_enriched and metrics_hourly_advanced (schema.sql, bottom section).
    #   5. Sanity-check: 9,000,000 rows; date range Jun 1 - Jul 5 2026; 'NAM' present (not 'NA').
    raise NotImplementedError("Lane A: implement load — see prompts/01-data-clickhouse.md")


if __name__ == "__main__":
    main()
