"""Local API and restricted, stateless public demo mode.

Public demo mode is safe for untrusted visitors ONLY because external data,
filesystem-based sources, strategy plugins and background jobs are disabled.
It is not a general-purpose authenticated multi-user trading API.
"""
from __future__ import annotations

import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .adapters import synthetic
from .engine import run_backtest
from .model import DataRequest, INTERVALS, Risk, iso_ms
from .service import execute, prepare
from .storage import Store
from .strategies import create_strategy

app = FastAPI(title="Universal Backtester", version="0.1.0")
_demo_slots = threading.BoundedSemaphore(value=2)


def public_demo() -> bool:
    return os.environ.get("UBT_PUBLIC_DEMO") == "1"


def private_only():
    if public_demo():
        raise HTTPException(403, "Public demo does not expose stored runs or scheduler jobs")


class BacktestPayload(BaseModel):
    data: dict = Field(default_factory=dict)
    risk: dict = Field(default_factory=dict)
    strategy: dict = Field(default_factory=dict)
    refresh: bool = False


def demo_backtest(config: dict) -> dict:
    """No database or external HTTP calls: fully synthetic, bounded simulation."""
    data = config.get("data", {})
    strategy = config.get("strategy", {})
    risk_data = config.get("risk", {})
    if data.get("provider", "demo") != "demo":
        raise ValueError("Public test site accepts synthetic demo data only")
    if data.get("include_funding") or config.get("refresh"):
        raise ValueError("Funding downloads and refresh are unavailable on the demo site")
    if strategy.get("type", "builtin") not in ("builtin", "pine"):
        raise ValueError("Public demo accepts built-in and safe Pine subset strategies only")
    if strategy.get("type", "builtin") == "builtin" and strategy.get("name", "sma_cross") not in ("buy_hold", "sma_cross", "rsi_revert", "breakout"):
        raise ValueError("Unknown built-in strategy")
    if strategy.get("type") == "pine":
        code = strategy.get("code", "")
        if not isinstance(code, str) or len(code) > 6000:
            raise ValueError("Public Pine editor limited to 6,000 characters")
    opts = strategy.get("options", {})
    if not isinstance(opts, dict) or len(opts) > 10:
        raise ValueError("Strategy options must be a small object")
    for key in ("fast", "slow", "period", "lookback"):
        if key in opts:
            v = opts[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 1 <= v <= 500:
                raise ValueError("Strategy lookback parameters must be in [1, 500]")
    for key in ("buy_below", "sell_above"):
        if key in opts:
            v = opts[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100:
                raise ValueError("RSI bounds must be in [0, 100]")
    if len(str(data.get("symbol", ""))) > 64:
        raise ValueError("Symbol exceeds maximum length")
    req, risk = prepare(config)
    params = (risk.initial_cash, risk.fee_bps, risk.slippage_bps, risk.leverage,
              risk.maintenance_margin_ratio)
    if not all(math.isfinite(v) for v in params):
        raise ValueError("Risk parameters must be finite")
    if risk.initial_cash > 10_000_000 or risk.leverage > 20:
        raise ValueError("Public demo allows at most 10m starting capital and 20x leverage")
    count = (iso_ms(req.end) - iso_ms(req.start)) // INTERVALS[req.timeframe]
    max_bars = 700 if strategy.get("type") == "pine" else 1500
    if not 2 <= count <= max_bars:
        raise ValueError(f"Public demo supports 2 to {max_bars:,} candles per run")
    bars = synthetic(req)
    if len(bars) < 2:
        raise ValueError("Not enough candles")
    result = run_backtest(bars, create_strategy(strategy), risk, req.timeframe)
    result["run_id"] = "demo-not-saved"
    result["warnings"] = [
        "PUBLIC DEMO: simulated candles, not real exchange prices; results are not market performance.",
        "Results and scheduled jobs are not saved on this public demo."
    ]
    result["coverage"] = {
        "first_ts": bars[0].ts, "last_ts": bars[-1].ts,
        "cached_bars": 0, "newly_fetched_bars": len(bars),
    }
    return result


@app.get("/")
def index():
    return FileResponse(Path(__file__).resolve().parent / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.1.0", "public_demo": public_demo(),
            "deployed_commit": os.environ.get("RENDER_GIT_COMMIT")}


@app.get("/api/sources")
def sources():
    if public_demo():
        return {
            "providers": ["demo"], "ccxt_exchanges_installed": [],
            "strategies": ["buy_hold", "sma_cross", "rsi_revert", "breakout", "pine_subset"],
            "public_demo": True,
            "limitations": "Synthetic data and restricted Pine subset only. No persistent runs, external data or jobs."
        }
    try:
        import ccxt
        cex = ccxt.exchanges
    except ImportError:
        cex = []
    return {"providers": ["demo", "csv", "ccxt", "hyperliquid", "yfinance"],
            "ccxt_exchanges_installed": cex,
            "strategies": ["buy_hold", "sma_cross", "rsi_revert", "breakout", "pine_subset"],
            "external_languages": "JSON-lines process strategy protocol (opt-in trusted host)",
            "public_demo": False,
            "limitations": "Provider coverage varies; Pine safe subset is not fully TradingView compatible."}


@app.get("/api/markets")
def markets(provider: str, q: str, exchange: str = "",
            market_type: str = "swap", limit: int = 30):
    private_only()
    from .catalog import search_markets
    try:
        return search_markets(provider, q, exchange, market_type, limit)
    except (ValueError, ImportError, RuntimeError) as err:
        raise HTTPException(422, detail=str(err)) from err


@app.post("/api/backtests/batch")
def backtests_batch(payload: dict):
    """Run common strategy independently across multiple exchanges/DEX venues."""
    private_only()
    from .batch import run_multi_market
    try:
        return run_multi_market(payload)
    except (ValueError, RuntimeError, PermissionError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@app.get("/api/candles")
def candles(provider: str, symbol: str, start: str, end: str,
            timeframe: str = "1d", exchange: str = "", market_type: str = "swap",
            max_points: int = 1200):
    """Query downsampled K lines for chart display only."""
    private_only()
    from .chart import read_candles
    try:
        req = DataRequest(provider=provider, exchange=exchange, symbol=symbol,
                          timeframe=timeframe, start=start, end=end, market_type=market_type)
        return read_candles(req, Store(), max_points=max_points)
    except (ValueError, RuntimeError, PermissionError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@app.post("/api/backtests")
def backtest(payload: BacktestPayload):
    try:
        if public_demo():
            if not _demo_slots.acquire(blocking=False):
                raise HTTPException(429, "Public demo busy; retry after current tests finish")
            try:
                return demo_backtest(payload.model_dump())
            finally:
                _demo_slots.release()
        return execute(payload.model_dump(), Store())
    except (ValueError, RuntimeError, ImportError, PermissionError, TimeoutError) as e:
        raise HTTPException(422, detail=str(e)) from e


@app.get("/api/backtests")
def runs(limit: int = 20):
    private_only()
    return Store().list_runs(limit)


@app.get("/api/backtests/{run_id}")
def run(run_id: str):
    private_only()
    item = Store().get_run(run_id)
    if item is None:
        raise HTTPException(404, "No such run")
    return item


@app.post("/api/jobs")
def add_job(payload: BacktestPayload):
    private_only()
    config = payload.model_dump()
    try:
        prepare(config)
        return {"job_id": Store().add_job(config), "schedule": "Daily (scheduler service)"}
    except (ValueError, PermissionError) as e:
        raise HTTPException(422, detail=str(e)) from e


@app.get("/api/jobs")
def jobs():
    private_only()
    return Store().jobs()


@app.patch("/api/jobs/{job_id}")
def set_job(job_id: str, active: bool):
    private_only()
    if not Store().set_job_active(job_id, active):
        raise HTTPException(404, "No such job")
    return {"job_id": job_id, "active": active}
