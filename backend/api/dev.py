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

def run_detect(metric: str, at: str, method: str | None = None, overrides: dict | None = None) -> dict:
    """Run detect() with IN-MEMORY config overrides, restoring config afterward (never writes disk)."""
    start = datetime.fromisoformat(at)
    det = config()["detection"]
    snapshot = copy.deepcopy(det)
    try:
        if method:
            det["method"] = method
        if overrides:
            det.update(overrides)
        anomaly, queries = detect(metric, Window(start=start, end=start + timedelta(hours=1)))
    finally:
        det.clear()
        det.update(snapshot)
    return {"method": method or snapshot["method"], "anomaly": anomaly.model_dump(), "queries": queries}


def run_compare(metric: str, at: str) -> list[dict]:
    return [run_detect(metric, at, method=m) for m in ("robust_z", "seasonal_ml")]


# ---- benchmarker: ground-truth harness (stubbed; localization -> JAL-77) ---

def benchmark_cases() -> list[dict]:
    return json.loads(_CASES.read_text())


def _case_target(window: str) -> datetime:
    # "2026-06-23..25" or "2026-06-21" -> the window's first day at noon (a placeholder hour).
    return datetime.fromisoformat(window.split("..")[0] + "T12:00")


def run_benchmark() -> list[dict]:
    out = []
    for case in benchmark_cases():
        target = _case_target(case["window"])
        try:
            res = run_detect(case["metric"], target.isoformat())
            a = res["anomaly"]
            out.append({
                "id": case["id"], "metric": case["metric"], "target": target.isoformat(),
                "detected": a["detected"], "score": round(a["score"], 2),
                "expect_segment": case["expect_segment"], "localization": "pending (JAL-77)",
            })
        except Exception as exc:  # noqa: BLE001
            out.append({"id": case["id"], "metric": case["metric"], "error": str(exc)})
    return out


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
def benchmark_run_endpoint() -> dict:
    return {"results": run_benchmark()}
