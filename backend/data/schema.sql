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
    e.event_time AS event_time, e.app_id AS app_id, e.geo_device_id AS geo_device_id,
    e.advertiser_id AS advertiser_id, e.ad_format AS ad_format,
    e.is_filled AS is_filled, e.is_impression AS is_impression, e.is_click AS is_click,
    e.revenue AS revenue,
    a.category AS category, a.publisher_tier AS publisher_tier,
    adv.vertical AS vertical, adv.campaign_type AS campaign_type,
    g.region AS region, g.country AS country, g.device_model AS device_model, g.os_version AS os_version
FROM ad_events e
LEFT JOIN apps_dim a USING (app_id)
LEFT JOIN advertisers_dim adv USING (advertiser_id)
LEFT JOIN geo_device_dim g USING (geo_device_id);

-- Hourly rollup for fast baselines/detection. Ratios stay sum/sum at read time.
CREATE TABLE IF NOT EXISTS hourly_summary
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
FROM events_full
GROUP BY ALL;

-- ---------------------------------------------------------------------------
-- JAL-73: system-of-record tables. ClickHouse stays the single datastore, so
-- investigation history is queryable in SQL and survives restarts.
-- ---------------------------------------------------------------------------

-- One row per investigation. ReplacingMergeTree keyed on investigation_id so
-- POST /narrate can rewrite the row in place (latest updated_at wins). Read with
-- FINAL — this table holds tens of rows, not millions.
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id  String,
    trace_id          String DEFAULT '',          -- Langfuse trace, survives across HTTP calls
    session_id        String DEFAULT '',          -- chat contextId, empty for direct API calls
    created_at        DateTime,
    updated_at        DateTime,
    metric            LowCardinality(String),
    window_start      DateTime,
    window_end        DateTime,
    primary_factor    LowCardinality(String) DEFAULT '',
    localized_segment String DEFAULT '',          -- JSON object
    detected          UInt8,
    narrated          UInt8 DEFAULT 0,
    bundle            String                      -- full EvidenceBundle JSON
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY investigation_id;

-- Chat sessions (kangavault contextId pattern). Title is generated lazily.
CREATE TABLE IF NOT EXISTS chat_sessions (
    context_id String,
    title      String DEFAULT '',
    created_at DateTime,
    updated_at DateTime
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY context_id;

-- Append-only conversation history. DateTime64(3) so turns within the same
-- second keep their order.
CREATE TABLE IF NOT EXISTS chat_turns (
    context_id String,
    role       LowCardinality(String),            -- user | assistant
    message    String,
    created_at DateTime64(3)
) ENGINE = MergeTree
ORDER BY (context_id, created_at);
