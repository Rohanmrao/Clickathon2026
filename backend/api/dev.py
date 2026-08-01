"""Dev/admin dashboard — data & table ops + a detection benchmarker, served at /dev.

LOCAL DEV ONLY. Mounted (in api/main.py) only when env ENABLE_DEV_DASHBOARD is truthy (default on).
Destructive ops (drop/load) require a typed confirm that is re-checked server-side, and table names
are allow-listed against the live SHOW TABLES set so a path can't smuggle arbitrary SQL.

Core logic lives in plain functions (unit-tested with the DB patched); the router is a thin wrapper.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from config import config, env
from data import store
from data.client import get_client, run_query
from models import Window
from rca import drilldown
from rca.bundle import build_bundle
from rca.detection import detect

_HTML = Path(__file__).resolve().parent / "dev_dashboard.html"
_CASES = Path(__file__).resolve().parent / "benchmark_cases.json"

_JOBS: dict[str, dict] = {}  # process-local load-job registry


def dev_enabled() -> bool:
    val = (env("ENABLE_DEV_DASHBOARD", "1") or "").strip().lower()
    return val not in ("", "0", "false", "no", "off")


# ---- tables & data ---------------------------------------------------------

def _table_names() -> list[str]:
    return [r[0] for r in run_query("SHOW TABLES")["rows"]]


def list_tables() -> list[dict]:
    out = []
    for name in _table_names():
        count = run_query(f"SELECT count() FROM {name}")["rows"][0][0]
        out.append({"name": name, "rows": count})
    return out


def preview_table(name: str, limit: int = 20) -> dict:
    if name not in _table_names():
        raise ValueError(f"unknown table: {name!r}")
    res = run_query(f"SELECT * FROM {name} LIMIT {int(limit)}")
    return {"columns": res["columns"], "rows": res["rows"]}


def drop_table(name: str, confirm: str) -> dict:
    if name not in _table_names():
        raise ValueError(f"unknown table: {name!r}")
    if confirm != name:
        raise ValueError("confirm must exactly equal the table name")
    get_client().command(f"DROP TABLE IF EXISTS {name}")
    return {"dropped": name}


# ---- load job (background) -------------------------------------------------

def start_load_job(confirm: str) -> dict:
    if confirm != "LOAD":
        raise ValueError('confirm must equal "LOAD"')
    job_id = uuid4().hex[:8]
    _JOBS[job_id] = {"status": "running", "log": "", "finished": False}
    threading.Thread(target=_run_load, args=(job_id,), daemon=True).start()
    return {"job_id": job_id}


def _run_load(job_id: str) -> None:
    buf = io.StringIO()
    try:
        from data.load import main as load_main
        with contextlib.redirect_stdout(buf):
            load_main()
        _JOBS[job_id].update(status="done", log=buf.getvalue(), finished=True)
    except Exception as exc:  # noqa: BLE001 — surface any load failure to the UI
        _JOBS[job_id].update(status="error", log=f"{buf.getvalue()}\nERROR: {exc}", finished=True)


def job_status(job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if job is None:
        raise ValueError(f"unknown job: {job_id!r}")
    return {"job_id": job_id, **job}


# ---- benchmarker: playground ----------------------------------------------

def _deep_merge(dst: dict, src: dict) -> None:
    """Recursive merge so a nested override (e.g. isolation_forest.features) keeps sibling keys."""
    for key, val in src.items():
        if isinstance(val, dict) and isinstance(dst.get(key), dict):
            _deep_merge(dst[key], val)
        else:
            dst[key] = val


# Each detector's score is on a DIFFERENT scale — surfacing this stops cross-method confusion.
_SCORE_KIND = {
    "robust_z": "robust z-score (|z| vs threshold)",
    "seasonal_ml": "residual z-score (|z| vs threshold)",
    "isolation_forest": "IsolationForest score (sign = verdict; ~-0.5..0.5)",
}


def _score_kind(method: str) -> str:
    return _SCORE_KIND.get(method, method)


def run_detect(metric: str, at: str, method: str | None = None, overrides: dict | None = None) -> dict:
    """Run detect() with IN-MEMORY config overrides, restoring config afterward (never writes disk)."""
    start = datetime.fromisoformat(at)
    det = config()["detection"]
    snapshot = copy.deepcopy(det)
    try:
        if method:
            det["method"] = method
        if overrides:
            _deep_merge(det, overrides)
        anomaly, queries = detect(metric, Window(start=start, end=start + timedelta(hours=1)))
    finally:
        det.clear()
        det.update(snapshot)
    resolved = method or snapshot["method"]
    return {"method": resolved, "score_kind": _score_kind(resolved), "anomaly": anomaly.model_dump(), "queries": queries}


def run_compare(metric: str, at: str) -> list[dict]:
    return [run_detect(metric, at, method=m) for m in ("robust_z", "seasonal_ml")]


# ---- benchmarker: ground-truth harness (stubbed; localization -> JAL-77) ---

def benchmark_cases() -> list[dict]:
    return json.loads(_CASES.read_text())


def _case_target(window: str) -> datetime:
    # "2026-06-23..25" or "2026-06-21" -> the window's first day at noon (detection sample hour).
    return datetime.fromisoformat(window.split("..")[0] + "T12:00")


def _case_window(window: str) -> Window:
    """Parse "2026-06-23..25" / "2026-06-21" into a [start, end) window (end exclusive, whole days)."""
    parts = window.split("..")
    start = datetime.fromisoformat(parts[0])
    if len(parts) == 2:
        end = datetime.fromisoformat(parts[0][:8] + f"{int(parts[1]):02d}") + timedelta(days=1)
    else:
        end = start + timedelta(days=1)
    return Window(start=start, end=end)


def localize(metric: str, start: str, end: str) -> dict:
    """Run the drill-down over a window and return the localized segment + path + queries."""
    window = Window(start=datetime.fromisoformat(start), end=datetime.fromisoformat(end))
    path, localized, queries = drilldown.drill(metric, metric, window, drilldown.baseline_window(window))
    return {"localized": localized, "path": [n.model_dump() for n in path], "queries": queries}


def run_benchmark(method: str | None = None, overrides: dict | None = None) -> list[dict]:
    """Detect (chosen method) AND localise (drill-down) each case; score both vs ground truth."""
    out = []
    for case in benchmark_cases():
        try:
            det = run_detect(case["metric"], _case_target(case["window"]).isoformat(), method=method, overrides=overrides)
            window = _case_window(case["window"])
            _, localized, _ = drilldown.drill(case["metric"], case["metric"], window, drilldown.baseline_window(window))
            expected = case["expect_segment"] or {}
            out.append({
                "id": case["id"], "metric": case["metric"], "method": det["method"], "score_kind": det["score_kind"],
                "detected": det["anomaly"]["detected"], "score": round(det["anomaly"]["score"], 2),
                "expect_segment": case["expect_segment"], "localized": localized,
                "hit": localized == expected,
            })
        except Exception as exc:  # noqa: BLE001
            out.append({"id": case["id"], "metric": case["metric"], "error": str(exc)})
    return out


# ---- mega comparison: every method x every case x several sample hours -------

_MEGA_METHODS = [
    {"label": "robust_z", "method": "robust_z", "overrides": None},
    {"label": "seasonal_ml", "method": "seasonal_ml", "overrides": None},
    {"label": "iforest/univariate", "method": "isolation_forest", "overrides": {"isolation_forest": {"features": "univariate"}}},
    {"label": "iforest/multivariate", "method": "isolation_forest", "overrides": {"isolation_forest": {"features": "multivariate"}}},
]


def _sample_hours(window: Window, k: int) -> list[datetime]:
    """k hours spread evenly across [start, end) — tests each method at several points, not one."""
    total = int((window.end - window.start).total_seconds() // 3600)
    if total <= 1:
        return [window.start]
    k = min(k, total)
    step = total / k
    return [window.start + timedelta(hours=int(step * i + step / 2)) for i in range(k)]


def run_mega(hours_per_case: int = 3) -> dict:
    """Run every detector variant against every case at several hours; localise once per case.

    Detection is the variable being compared (method x hour); localisation is deterministic so it's
    computed once per case and reused. Returns per-(variant,case) rows + a per-variant summary.
    """
    cases = benchmark_cases()
    localized_by_case = {}
    for case in cases:
        window = _case_window(case["window"])
        try:
            _, localized, _ = drilldown.drill(case["metric"], case["metric"], window, drilldown.baseline_window(window))
        except Exception:  # noqa: BLE001
            localized = None
        localized_by_case[case["id"]] = localized

    rows = []
    for variant in _MEGA_METHODS:
        for case in cases:
            hours = _sample_hours(_case_window(case["window"]), hours_per_case)
            detected, scores = 0, []
            for hour in hours:
                try:
                    r = run_detect(case["metric"], hour.isoformat(), method=variant["method"], overrides=variant["overrides"])
                    detected += 1 if r["anomaly"]["detected"] else 0
                    scores.append(r["anomaly"]["score"])
                except Exception:  # noqa: BLE001, S110 -- a failed hour just doesn't count
                    pass
            localized = localized_by_case[case["id"]]
            rows.append({
                "variant": variant["label"], "method": variant["method"], "score_kind": _score_kind(variant["method"]),
                "case": case["id"], "metric": case["metric"], "detected": detected, "hours": len(hours),
                "mean_score": round(sum(scores) / len(scores), 3) if scores else None,
                "localized": localized, "hit": localized == (case["expect_segment"] or {}),
            })

    summary = []
    for variant in _MEGA_METHODS:
        vrows = [r for r in rows if r["variant"] == variant["label"]]
        det, tot = sum(r["detected"] for r in vrows), sum(r["hours"] for r in vrows)
        summary.append({
            "variant": variant["label"], "score_kind": _score_kind(variant["method"]),
            "detection_rate": round(det / tot, 3) if tot else 0.0,
            "cases_fired": sum(1 for r in vrows if r["detected"] > 0), "cases": len(vrows),
            "localized_correct": sum(1 for r in vrows if r["hit"]),
        })
    return {"hours_per_case": hours_per_case, "rows": rows, "summary": summary}


def start_mega_job(hours_per_case: int = 3) -> dict:
    job_id = uuid4().hex[:8]
    _JOBS[job_id] = {"status": "running", "log": "", "finished": False, "result": None}
    threading.Thread(target=_run_mega_job, args=(job_id, hours_per_case), daemon=True).start()
    return {"job_id": job_id}


def _run_mega_job(job_id: str, hours_per_case: int) -> None:
    try:
        result = run_mega(hours_per_case)
        _JOBS[job_id].update(status="done", finished=True, result=result, log=f"{len(result['rows'])} rows")
    except Exception as exc:  # noqa: BLE001
        _JOBS[job_id].update(status="error", finished=True, log=str(exc))


# ---- full engine: build_bundle per case (the real end-to-end EvidenceBundle) ----

def run_engine_benchmark() -> list[dict]:
    """Run the WHOLE engine (build_bundle) per ground-truth case and summarize each bundle.

    Method-independent (build_bundle uses the incident scanner + deterministic decompose/drill), so
    it's one bundle per case — the end-to-end artifact, not just detect/drill."""
    out = []
    for case in benchmark_cases():
        window = _case_window(case["window"])
        row = {"id": case["id"], "metric": case["metric"],
               "start": window.start.isoformat(), "end": window.end.isoformat()}  # for click-to-view
        try:
            b = build_bundle(case["metric"], window)
            row.update({
                "detected": b.anomaly.detected, "score": round(b.anomaly.score, 2),
                "primary_factor": b.factor_decomposition.primary_factor,
                "localized": b.localized_segment, "hit": b.localized_segment == (case["expect_segment"] or {}),
                "ruled_out": [r.hypothesis for r in b.ruled_out], "n_queries": len(b.queries),
            })
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)
        out.append(row)
    return out


def full_bundle(metric: str, start: str, end: str) -> dict:
    """Build one bundle and return it as schema-shaped JSON (for the click-to-view drawer)."""
    window = Window(start=datetime.fromisoformat(start), end=datetime.fromisoformat(end))
    return build_bundle(metric, window).model_dump(mode="json", by_alias=True, exclude_none=True)


def start_engine_job() -> dict:
    job_id = uuid4().hex[:8]
    _JOBS[job_id] = {"status": "running", "log": "", "finished": False, "result": None}
    threading.Thread(target=_run_engine_job, args=(job_id,), daemon=True).start()
    return {"job_id": job_id}


def _run_engine_job(job_id: str) -> None:
    try:
        rows = run_engine_benchmark()
        _JOBS[job_id].update(status="done", finished=True, result={"rows": rows}, log=f"{len(rows)} bundles")
    except Exception as exc:  # noqa: BLE001
        _JOBS[job_id].update(status="error", finished=True, log=str(exc))


# ---- router (thin wrapper; ValueError -> 400) ------------------------------

router = APIRouter(prefix="/dev", tags=["dev"])


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class DropReq(BaseModel):
    confirm: str


class LoadReq(BaseModel):
    confirm: str


class DetectReq(BaseModel):
    metric: str = "revenue"
    at: str = "2026-07-04T10:00"
    method: str | None = None
    overrides: dict | None = None


class CompareReq(BaseModel):
    metric: str = "revenue"
    at: str = "2026-07-04T10:00"


class BenchmarkReq(BaseModel):
    method: str | None = None
    overrides: dict | None = None


class LocalizeReq(BaseModel):
    metric: str = "fill_rate"
    start: str = "2026-06-23"
    end: str = "2026-06-26"


@router.get("", response_class=HTMLResponse)
def dashboard() -> str:
    return _HTML.read_text(encoding="utf-8")


@router.get("/tables")
def tables() -> dict:
    return {"tables": list_tables()}


@router.get("/table/{name}")
def table_preview(name: str, limit: int = 20) -> dict:
    return _guard(preview_table, name, limit)


@router.post("/table/{name}/drop")
def table_drop(name: str, req: DropReq) -> dict:
    return _guard(drop_table, name, req.confirm)


@router.post("/load")
def load(req: LoadReq) -> dict:
    return _guard(start_load_job, req.confirm)


@router.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    return _guard(job_status, job_id)


@router.get("/runs")
def runs(limit: int = 50) -> dict:
    return {"runs": store.list_investigations(limit)}


@router.get("/runs/{investigation_id}")
def run_detail(investigation_id: str) -> dict:
    bundle = store.load_bundle(investigation_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"no investigation {investigation_id!r}")
    return bundle.model_dump(mode="json")


@router.post("/detect")
def detect_endpoint(req: DetectReq) -> dict:
    return _guard(run_detect, req.metric, req.at, req.method, req.overrides)


@router.post("/compare")
def compare_endpoint(req: CompareReq) -> dict:
    return {"results": _guard(run_compare, req.metric, req.at)}


@router.get("/benchmark/cases")
def benchmark_cases_endpoint() -> dict:
    return {"cases": benchmark_cases()}


@router.post("/benchmark/run")
def benchmark_run_endpoint(req: BenchmarkReq) -> dict:
    return {"results": run_benchmark(req.method, req.overrides)}


@router.post("/localize")
def localize_endpoint(req: LocalizeReq) -> dict:
    return _guard(localize, req.metric, req.start, req.end)


class MegaReq(BaseModel):
    hours_per_case: int = 3


@router.post("/mega")
def mega_endpoint(req: MegaReq) -> dict:
    return start_mega_job(req.hours_per_case)  # background job; poll /dev/jobs/{id} for result


@router.post("/engine")
def engine_endpoint() -> dict:
    return start_engine_job()  # background job; poll /dev/jobs/{id} for result


class BundleReq(BaseModel):
    metric: str = "revenue"
    start: str = "2026-06-21"
    end: str = "2026-06-22"


@router.post("/bundle")
def bundle_endpoint(req: BundleReq) -> dict:
    return _guard(full_bundle, req.metric, req.start, req.end)
