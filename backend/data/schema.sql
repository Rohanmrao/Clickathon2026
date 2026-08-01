-- Lane A: ClickHouse schema. Run top-to-bottom against your Cloud service.
-- Table names here match the LIVE database and config.json. Ids as LowCardinality(String);
-- is_* as UInt8; revenue Float64; NAM (not NA) for North America.

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

CREATE TABLE IF NOT EXISTS apps_dim (
    app_id         LowCardinality(String),
    category       LowCardinality(String),
    publisher_tier LowCardinality(String)
) ENGINE = MergeTree ORDER BY app_id;

CREATE TABLE IF NOT EXISTS advertisers_dim (
    advertiser_id LowCardinality(String),
    vertical      LowCardinality(String),
    campaign_type LowCardinality(String)
) ENGINE = MergeTree ORDER BY advertiser_id;

CREATE TABLE IF NOT EXISTS geo_device_dim (
    geo_device_id LowCardinality(String),
    region        LowCardinality(String),
    country       LowCardinality(String),
    device_model  LowCardinality(String),
    os_version    LowCardinality(String)
) ENGINE = MergeTree ORDER BY geo_device_id;

-- Denormalized analytical table: every drill-down is a single-table GROUP BY, no joins in recursion.
CREATE TABLE IF NOT EXISTS events_full
ENGINE = MergeTree
ORDER BY (event_time, country, os_version, app_id)
AS
SELECT
    e.event_time, e.app_id, e.geo_device_id, e.advertiser_id, e.ad_format,
    e.is_filled, e.is_impression, e.is_click, e.revenue,
    a.category, a.publisher_tier,
    adv.vertical, adv.campaign_type,
    g.region, g.country, g.device_model, g.os_version
FROM ad_events e
LEFT JOIN apps_dim a USING (app_id)
LEFT JOIN advertisers_dim adv USING (advertiser_id)
LEFT JOIN geo_device_dim g USING (geo_device_id);

-- Advanced hourly rollup (metrics_hourly_advanced): raw sums + zero-safe ratio columns.
-- NOT created here — it is built from config + the shared metric formulas so there is one
-- definition, not a copy that can drift. Rebuild it any time with:
--     python -m data.build_advanced
