-- Lane A: ClickHouse schema. Run top-to-bottom against your Cloud service.
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

-- Denormalized analytical table: every drill-down is a single-table GROUP BY, no joins in recursion.
CREATE TABLE IF NOT EXISTS events_enriched
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
LEFT JOIN apps a USING (app_id)
LEFT JOIN advertisers adv USING (advertiser_id)
LEFT JOIN geo_device g USING (geo_device_id);

-- Hourly rollup for fast baselines/detection. Ratios stay sum/sum at read time.
CREATE TABLE IF NOT EXISTS metrics_hourly
ENGINE = SummingMergeTree
ORDER BY (hour, region, country, os_version, device_model, ad_format, category, publisher_tier, vertical, campaign_type, app_id, advertiser_id)
AS
SELECT
    toStartOfHour(event_time) AS hour,
    region, country, os_version, device_model, ad_format,
    category, publisher_tier, vertical, campaign_type, app_id, advertiser_id,
    count()            AS requests,
    sum(is_filled)     AS fills,
    sum(is_impression) AS impressions,
    sum(is_click)      AS clicks,
    sum(revenue)       AS revenue
FROM events_enriched
GROUP BY ALL;
