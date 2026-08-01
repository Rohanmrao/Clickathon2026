-- Lane A: DERIVED tables. Built AFTER raw tables are loaded (load.py drops + recreates these).

-- Denormalized analytical table: every drill-down is a single-table GROUP BY, no joins in recursion.
CREATE TABLE events_enriched
ENGINE = MergeTree
ORDER BY (event_time, country, os_version, app_id)
AS
SELECT
    event_time, app_id, geo_device_id, advertiser_id, ad_format,
    is_filled, is_impression, is_click, revenue,
    category, publisher_tier,
    vertical, campaign_type,
    region, country, device_model, os_version
FROM ad_events
LEFT JOIN apps USING (app_id)
LEFT JOIN advertisers USING (advertiser_id)
LEFT JOIN geo_device USING (geo_device_id);

-- Hourly rollup for fast baselines/detection. Ratios stay sum/sum at read time.
CREATE TABLE metrics_hourly
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
