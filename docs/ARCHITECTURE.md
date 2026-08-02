# Architecture

**Automated Root-Cause Analyst** · Jalagaara Gang · InMobi track

The system answers one question — *which segment caused this metric to move?* — in three stages,
all of them computed in ClickHouse, with the LLM confined to writing the final sentence.

## The pipeline

```
                    ┌───────────────── API LAYER ─────────────────┐
   browser ───────▶ │  /investigate   /narrate   /bundle          │
   LibreChat ─────▶ │  /v1/chat/completions  (OpenAI-compatible)  │
                    └───────────────────┬─────────────────────────┘
                                        │
        ┌───────────────────────────────┴───────────────────────────────┐
        │                        RCA ENGINE                             │
        │                                                               │
        │   1. DETECTION          2. DECOMPOSITION      3. DRILL-DOWN   │
        │   did it move?          which factor?         which segment?  │
        │   robust_z /            Revenue = Requests    counterfactual  │
        │   seasonal_ml /         × FillRate × eCPM     gap-closure     │
        │   isolation_forest      (log-additive)        ÷ volume share  │
        └───────────────────────────────┬───────────────────────────────┘
                                        │   every stage is SQL
                        ┌───────────────▼───────────────┐
                        │          CLICKHOUSE           │
                        │  ad_events        9M raw      │
                        │  events_full      enriched    │
                        │  hourly_summary   rollup      │
                        │  investigations   evidence    │
                        └───────────────┬───────────────┘
                                        │
                        ┌───────────────▼───────────────┐
                        │   NARRATOR                    │
                        │   bundle → 3–5 sentences      │
                        │   guardrail verifies numbers  │
                        └───────────────┬───────────────┘
                                        │
                              Langfuse: one trace,
                              SQL spans nested inside
```

Everything flows through one object, the **Evidence Bundle**
([`contracts/evidence_bundle.schema.json`](../contracts/evidence_bundle.schema.json)): the
anomaly, the factor split, the drill-down path, the ruled-out list, and `queries[]` — the SQL
that produced every number, so any figure can be recomputed independently.

## Where the analysis runs

**In ClickHouse, not the LLM.** Each drill-down level issues a `GROUP BY` per candidate dimension
and scores every segment value with a counterfactual:

> Restore this segment's component sums (`requests`, `fills`, `impressions`, `clicks`, `revenue`)
> to their baseline, recompute the population metric, and measure how much of the total gap
> closes.

That gap-closure fraction is then divided by the segment's share of the metric's **volume** — its
denominator, so eCPM is weighted by impressions rather than requests. The result is **lift**:

```
lift ≈ 1     the segment is merely large — it closes about its own share of the gap
lift ≫ 1     the segment closes far more than its size explains — a real culprit
```

The recursion descends into the top disproportionate contributor, adds it to a cumulative filter,
and repeats until nothing remaining is both material and disproportionate — at which point a
uniform, population-wide move correctly localises to **nothing**.

That distinction is the core design decision. Ranking on raw contribution instead of lift picks
whichever segment carries the most traffic, because for a uniform effect contribution share
simply equals traffic share. Measured against the four planted anomalies, raw contribution scored
**0/4**, expanding `Android 15` into `Android 15 AND tier_2 AND EU AND Galaxy A54` — three extra
conditions that explain nothing and would each be wrong against an answer key. Lift scores
**4/4**.

## Detection methodology

Three interchangeable detectors sit behind one contract (`rca/detection.py`), chosen by
`config.detection.method`, all returning the same `Anomaly` shape so nothing downstream cares
which ran:

| Detector | Baseline | Notes |
|---|---|---|
| `robust_z` | Same weekday + hour, trailing N weeks | Median centre, MAD spread. Default. |
| `seasonal_ml` | Per-(weekday × hour) profile over all history | Pools hundreds of points instead of 3 |
| `isolation_forest` | scikit-learn, per-hour feature vector | Catches unusual metric *combinations* |

Two decisions matter more than the choice of detector.

**Thresholds are calibrated, not hardcoded** (`data/calibration.py`). Each metric's minimum
effect size is derived from its own natural volatility — measured on like-for-like hours — because
"how big is big" is metric-specific. On this dataset that yields ≈2.8% for fill_rate and ≈84% for
CTR: with only 74,940 clicks across 9M events, daily CTR swings wildly and a shared threshold
would either drown in false positives or miss everything.

**Detection runs per factor, not on revenue alone.** Jun 29–30 are the two highest-revenue days
in the dataset while APAC fill rate halved — organic traffic growth masked a real regression. A
revenue-only detector never sees it.

Multi-day anomalies are merged into a single incident before investigation
(`rca/incidents.py`); at hourly grain a three-day anomaly would otherwise raise ~72 separate
alerts and produce 72 near-identical bundles.

## Diagnosis, and why it can be trusted

The narrator receives a completed Evidence Bundle and writes 3–5 sentences. It has no database
access and performs no arithmetic.

`narrator/guardrail.py` then extracts every number from the prose and rejects any that is not
present in the evidence. It also rejects a genuine number wearing invented units — a live run
produced `$18.33M` from a bundle value of `18.33`, every digit real but the magnitude inflated a
millionfold. Digit-matching alone passed it; the guardrail now fails it.

The verdict is recorded on the bundle as `narrative_verification`, so a failed check is visible
rather than silent.

## OSS Stack integration

**Langfuse** (self-hosted v3) is wired at the layer that carries evidence, not as a wrapper
around the LLM call:

- `data.client.run_query` emits a span per SQL statement, nesting under the investigation root
  automatically via OpenTelemetry context — so a trace shows the **real query sequence**
- `trace_id` is persisted with the bundle, because `/investigate` and `/narrate` are separate
  HTTP calls; without it the LLM generation would open an orphaned second trace and the SQL
  steps would appear unrelated to the diagnosis
- `Query.langfuse_span_id` cross-references both ways — from any number in a diagnosis to the
  span that produced it, and back
- Chat turns group into a Langfuse **session**, so a conversation reads as one thread

**LibreChat** consumes an OpenAI-compatible endpoint. `POST /v1/chat/completions` returns a valid
chat completion with the Evidence Bundle riding alongside in the same payload — OpenAI clients
ignore unknown keys, so one endpoint serves both LibreChat and the dashboard with no adapter.

## Data model

| Table | Role |
|---|---|
| `ad_events` | 9M raw events as delivered |
| `events_full` | Denormalized — dimensions flattened via `LEFT JOIN` |
| `hourly_summary` | Pre-aggregated sums per hour × dimension |
| `investigations` | Completed bundles, `ReplacingMergeTree` |

`advertiser_id` is empty on all 1,972,090 unfilled requests, so advertiser dimensions exist only
*after* a fill. An inner join silently returns `fill_rate = 1.0`; every join is therefore a
`LEFT JOIN`, and fill-rate drill-downs never scan advertiser dimensions.

Ratios are always `sum / sum` over the group, never an average of per-row ratios — averaging
ratios skews results by up to 2.8% here, and differently per region, which would distort exactly
the segment comparisons the drill-down depends on.

Storing results back into ClickHouse keeps it the single datastore: investigation history is
itself queryable in SQL.

## Deployment

Docker Compose on a single EC2 host, behind nginx with Let's Encrypt. Secrets live in **SSM
Parameter Store** as `SecureString`, read at boot through the instance's IAM role — never in the
repo, never in the image, and no AWS keys on the host. Bedrock narration authenticates through
the same role. Rotation is: update the parameter, reboot.

See [`deploy/`](../deploy/) for the bootstrap script, IAM policy and nginx config.
