"""ML detector: scikit-learn IsolationForest over per-hour features.

An actual trained estimator (unlike seasonal_ml's hand-rolled median model). Unsupervised — it fits
on all historical hours and scores the target hour's outlierness. Two feature modes, toggleable via
config.detection.isolation_forest.features:

  * univariate   — per hour: [value, seasonal-expected, residual, hour-of-day, weekday] for the chosen
                   metric. Detection = the forest flags it AND the metric moved >= min_pct_delta.
  * multivariate — per hour: the ratio vector (fill_rate, ctr, ecpm, ...). Flags hours whose metric
                   COMBINATION is unusual even if the single metric looks normal (no pct floor).

Deterministic given random_state; the pulled series SQL is logged for traceability. ClickHouse
aggregates to hourly; sklearn only sees the small hourly frame.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sklearn.ensemble import IsolationForest

from config import config
from data.client import run_query
from metrics import metric_sql
from models import Anomaly, Window
from rca.robust import pct_delta

_HOURLY = config()["clickhouse"]["hourly_table"]

_PARAM_KEYS = ("n_estimators", "contamination", "random_state", "min_pct_delta")


def _seasonal(df: pd.DataFrame) -> pd.Series:
    cell = list(zip(df["hour"].dt.dayofweek, df["hour"].dt.hour))
    return df.assign(_cell=cell).groupby("_cell")["value"].transform("median")


def _feature_matrix(df: pd.DataFrame, seasonal: pd.Series, mode: str, feature_cols: list[str]) -> pd.DataFrame:
    if mode == "multivariate":
        return df[feature_cols].astype(float)
    return pd.DataFrame({
        "value": df["value"], "seasonal": seasonal, "residual": df["value"] - seasonal,
        "hod": df["hour"].dt.hour, "wd": df["hour"].dt.dayofweek,
    })


def score_frame(df: pd.DataFrame, target_hour: datetime, mode: str, feature_cols: list[str], params: dict) -> Anomaly:
    """Fit IsolationForest on the frame and score `target_hour` (pure — no DB)."""
    df = df.reset_index(drop=True).copy()
    df["hour"] = pd.to_datetime(df["hour"])
    seasonal = _seasonal(df)
    features = _feature_matrix(df, seasonal, mode, feature_cols).fillna(0.0)

    model = IsolationForest(
        n_estimators=params.get("n_estimators", 200),
        contamination=params.get("contamination", "auto"),
        random_state=params.get("random_state", 42),
    ).fit(features)

    idx = df.index[df["hour"] == pd.Timestamp(target_hour)]
    if len(idx) == 0:
        raise ValueError(f"target hour {target_hour} not present in series")
    i = int(idx[0])
    xt = features.iloc[[i]]
    score = float(-model.decision_function(xt)[0])   # > 0 => more anomalous
    flagged = int(model.predict(xt)[0]) == -1

    observed = float(df["value"].iloc[i])
    expected = float(seasonal.iloc[i])
    pct = pct_delta(observed, expected)
    # univariate ties detection to the metric's own move; multivariate is about the combination.
    detected = flagged and (abs(pct) >= params.get("min_pct_delta", 0.05)) if mode == "univariate" else flagged

    return Anomaly(
        detected=detected, observed=observed, expected=expected,
        abs_delta=observed - expected, pct_delta=pct, score=score,
        direction="drop" if observed < expected else "spike",
    )


def _series_sql(metric: str, mode: str, feature_cols: list[str]) -> str:
    cols = [f"{metric_sql(metric, 'rollup')} AS value"]
    if mode == "multivariate":
        cols += [f"{metric_sql(name, 'rollup')} AS {name}" for name in feature_cols]
    # A ratio col like `sum(requests) AS requests` shadows the source column inside other ratios;
    # prefer the column so sum(requests) isn't read as sum(sum(requests)) (illegal nested aggregation).
    return (f"SELECT hour, {', '.join(cols)} FROM {_HOURLY} GROUP BY hour ORDER BY hour "
            f"SETTINGS prefer_column_name_to_alias = 1")


def run(metric: str, target: Window) -> tuple[Anomaly, list[dict]]:
    """Score the GLOBAL metric at the target hour via IsolationForest. Returns (Anomaly, queries)."""
    cfg = config()["detection"]["isolation_forest"]  # read fresh so in-memory overrides take effect
    mode = cfg["features"]
    feature_cols = cfg["feature_columns"]
    res = run_query(_series_sql(metric, mode, feature_cols))
    df = pd.DataFrame(res["rows"], columns=res["columns"])
    params = {k: cfg[k] for k in _PARAM_KEYS}
    anomaly = score_frame(df, target.start, mode, feature_cols, params)
    query = {"id": "q_iforest_features", "sql": res["resolved_sql"],
             "result_summary": {"mode": mode, "n_hours": len(df), "score": anomaly.score}}
    return anomaly, [query]
