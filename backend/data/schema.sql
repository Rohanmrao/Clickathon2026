-- Lane A: RAW tables (fact + dimensions). Loaded first, then data, then derived.sql.
-- Ids as LowCardinality(String); is_* as UInt8; revenue Float64; NAM (not NA) for North America.

CREATE TABLE IF NOT EXISTS ad_events (
    event_time     DateTime,
    app_id         LowCardinality(String),
    geo_device_id  LowCardinality(String),
    advertiser_id  LowCardinality(String),   -- empty on unfilled requests
    ad_format      LowCardinality(String),
    is_filled      UInt8,
    is_impression  UInt8,
    is_click       UInt8,
    revenue        Float64
) ENGINE = MergeTree
ORDER BY (event_time, app_id);

CREATE TABLE IF NOT EXISTS apps (
    app_id         LowCardinality(String),
    category       LowCardinality(String),
    publisher_tier LowCardinality(String)
) ENGINE = MergeTree ORDER BY app_id;

CREATE TABLE IF NOT EXISTS advertisers (
    advertiser_id LowCardinality(String),
    vertical      LowCardinality(String),
    campaign_type LowCardinality(String)
) ENGINE = MergeTree ORDER BY advertiser_id;

CREATE TABLE IF NOT EXISTS geo_device (
    geo_device_id LowCardinality(String),
    region        LowCardinality(String),
    country       LowCardinality(String),
    device_model  LowCardinality(String),
    os_version    LowCardinality(String)
) ENGINE = MergeTree ORDER BY geo_device_id;
