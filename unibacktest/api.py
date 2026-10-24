"""Local-first UI and REST API. Do not expose unauthenticated to the Internet."""
from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from .model import DataRequest
from .storage import Store
from .service import execute, prepare

app = FastAPI(title="Universal Backtester", version="0.1.0")


class BacktestPayload(BaseModel):
    data: dict = Field(default_factory=dict)
    risk: dict = Field(default_factory=dict)
    strategy: dict = Field(default_factory=dict)
    refresh: bool = False


@app.get("/")
def index():
    return FileResponse(Path(__file__).resolve().parent / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.1.0"}


@app.get("/api/sources")
def sources():
    try:
        import ccxt
        cex = ccxt.exchanges
    except ImportError:
        cex = []
    return {"providers": ["demo", "csv", "ccxt", "hyperliquid", "yfinance"],
            "ccxt_exchanges_installed": cex,
            "strategies": ["buy_hold", "sma_cross", "rsi_revert", "breakout"],
            "external_languages": "JSON-lines process strategy protocol (opt-in trusted host)",
            "limitations": "Provider coverage varies; no native Pine interpreter."}


@app.post("/api/backtests")
def backtest(payload: BacktestPayload):
    try:
        return execute(payload.model_dump(), Store())
    except (ValueError, RuntimeError, ImportError, PermissionError, TimeoutError) as e:
        raise HTTPException(422, detail=str(e)) from e


@app.get("/api/backtests")
def runs(limit: int = 20):
    return Store().list_runs(limit)


@app.get("/api/backtests/{run_id}")
def run(run_id: str):
    item = Store().get_run(run_id)
    if item is None:
        raise HTTPException(404, "No such run")
    return item


@app.post("/api/jobs")
def add_job(payload: BacktestPayload):
    config = payload.model_dump()
    try:
        prepare(config)
        # Validate execution permission and paths only when task executes.
        return {"job_id": Store().add_job(config), "schedule": "Daily (scheduler service)"}
    except (ValueError, PermissionError) as e:
        raise HTTPException(422, detail=str(e)) from e


@app.get("/api/jobs")
def jobs():
    return Store().jobs()


@app.patch("/api/jobs/{job_id}")
def set_job(job_id: str, active: bool):
    if not Store().set_job_active(job_id, active):
        raise HTTPException(404, "No such job")
    return {"job_id": job_id, "active": active}
