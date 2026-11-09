"""NetLens local agent.

Runs network measurements on this machine, analyzes them with a rule-based
engine, and serves the dashboard at http://127.0.0.1:8000.
"""

from __future__ import annotations

import csv
import io
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import analysis
import measure
import storage

VERSION = "0.2.0"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# The agent only listens on localhost. These checks also stop other websites
# open in your browser from starting scans or reading results (CSRF / DNS rebinding).
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost"}

_latest: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(title="NetLens Agent", version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "NetLens only accepts requests to 127.0.0.1 or localhost."}, status_code=403)
    origin = request.headers.get("origin")
    if origin:
        origin_host = origin.split("://", 1)[-1].rsplit(":", 1)[0]
        if origin_host not in ALLOWED_ORIGIN_HOSTS:
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
    return await call_next(request)


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

def _empty_metrics() -> dict[str, Any]:
    return {"errors": {}}


def _merge(metrics: dict[str, Any], partial: dict[str, Any]) -> None:
    errors = partial.get("errors") or {}
    metrics["errors"].update({key: value for key, value in errors.items() if value})
    metrics.update({key: value for key, value in partial.items() if key != "errors"})


def _finish(metrics: dict[str, Any]) -> dict[str, Any]:
    global _latest
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        **analysis.analyze(metrics),
    }
    if "ping" in metrics["errors"]:
        # Without a ping there's nothing trustworthy to score; don't log it as a scan.
        result["saved"] = False
    else:
        result["id"] = storage.save_scan(result)
        result["saved"] = True
    _latest = result
    return result


def _scan_events(include_throughput: bool) -> Iterator[str]:
    metrics = _empty_metrics()
    try:
        for stage, partial in measure.run_scan(include_throughput):
            _merge(metrics, partial)
            yield _sse("stage", {"stage": stage, "metrics": metrics})
        yield _sse("result", _finish(metrics))
    except Exception as exc:  # report, don't hang the browser
        yield _sse("error", {"detail": f"Scan failed: {exc}"})


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@app.get("/health")
def health():
    return {"status": "ok", "service": "NetLens Agent", "version": VERSION}


@app.post("/api/v1/scan")
def scan(throughput: bool = True):
    metrics = _empty_metrics()
    for _stage, partial in measure.run_scan(throughput):
        _merge(metrics, partial)
    return _finish(metrics)


@app.get("/api/v1/scan/stream")
def scan_stream(throughput: bool = True):
    return StreamingResponse(
        _scan_events(throughput),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v1/scan/latest")
def latest_scan():
    if _latest is None:
        return Response(status_code=204)
    return _latest


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------

class TaskQuestion(BaseModel):
    task: str = Field(min_length=1, max_length=200)


@app.post("/api/v1/check-task")
def check_task(question: TaskQuestion):
    if _latest is None:
        raise HTTPException(status_code=409, detail="Run a scan first.")
    task = analysis.match_task(question.task)
    if task is None:
        return {
            "matched": False,
            "question": question.task,
            "verdict": "unknown",
            "reason": "NetLens doesn't recognise that task yet. Try naming the app, like Zoom, WhatsApp or YouTube.",
        }
    return {"matched": True, "question": question.task, **analysis.evaluate_task(task, _latest["metrics"])}


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------

@app.get("/api/v1/history")
def get_history(limit: int = Query(50, ge=1, le=1000)):
    return storage.history(limit)


@app.get("/api/v1/history.csv")
def export_history():
    rows = storage.history(10_000)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["id", *storage.COLUMNS])
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="netlens-history.csv"'},
    )


@app.delete("/api/v1/history")
def delete_history():
    return {"deleted": storage.clear_history()}


# Dashboard. Mounted last so API routes take precedence.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="dashboard")
