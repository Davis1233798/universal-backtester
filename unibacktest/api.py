"""Local API and restricted, stateless public demo mode.

Public demo mode is safe for untrusted visitors ONLY because external data,
filesystem-based sources, strategy plugins and background jobs are disabled.
It is not a general-purpose authenticated multi-user trading API.
"""
from __future__ import annotations

import math
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .adapters import synthetic
from .engine import run_backtest
from .model import DataRequest, INTERVALS, Risk, iso_ms
from .service import execute, prepare
from .storage import Store
from .strategies import create_strategy

app = FastAPI(title="Universal Backtester", version="0.1.0",
              docs_url=None, redoc_url=None, openapi_url=None)
# Vite bundles JavaScript and CSS locally; no remote JS CDN can read API tokens.
app.mount("/assets", StaticFiles(directory=str(Path(__file__).resolve().parent / "static" / "app" / "assets"), check_dir=False), name="assets")
_demo_slots = threading.BoundedSemaphore(value=2)


def public_demo() -> bool:
    return os.environ.get("UBT_PUBLIC_DEMO") == "1"


def private_only():
    if public_demo():
        raise HTTPException(403, "Public demo does not expose stored runs or scheduler jobs")



@app.middleware("http")
async def enforce_api_access(request: Request, call_next):
    """Fail closed for every current or future API endpoint.

    Explicit PUBLIC demo allows only synthetic execution and metadata.
    Everything else needs a >=32 character secret and exact Bearer token.
    """
    path=request.url.path
    if path.startswith("/api/") and path != "/api/health":
        if public_demo():
            safe=(path=="/api/sources" and request.method=="GET" or
                  path=="/api/backtests" and request.method=="POST")
            if not safe:
                return JSONResponse({"detail":"Not available in public demo"},status_code=403)
        else:
            expected=os.environ.get("UBT_API_TOKEN","")
            if len(expected)<32:
                return JSONResponse({"detail":"Private API locked: configure UBT_API_TOKEN (32+ characters)"},status_code=503)
            authorization=request.headers.get("authorization","")
            if (not authorization.startswith("Bearer ") or
                not secrets.compare_digest(authorization[7:],expected)):
                return JSONResponse({"detail":"Bearer authentication required"},status_code=401,
                                    headers={"WWW-Authenticate":"Bearer"})
    response=await call_next(request)
    if path.startswith("/api/"):
        response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Referrer-Policy"]="no-referrer"
    return response


class BacktestPayload(BaseModel):
    streaming: bool = False
    data: dict = Field(default_factory=dict)
    risk: dict = Field(default_factory=dict)
    strategy: dict = Field(default_factory=dict)
    refresh: bool = False


def demo_backtest(config: dict) -> dict:
    """No database or external HTTP calls: fully synthetic, bounded simulation."""
    data = config.get("data", {})
    strategy = config.get("strategy", {})
    risk_data = config.get("risk", {})
    if config.get("streaming"):
        raise ValueError("Public synthetic demo does not support SQLite streaming API")
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
    # Only the public synthetic demonstration has a configurable CPU/resource
    # budget. Real market history is never clipped by this setting.
    budget = int(os.environ.get("UBT_PUBLIC_DEMO_MAX_BARS", "50000"))
    if not 2 <= count <= budget:
        raise ValueError(
            f"Public demo resource budget: {budget:,} synthetic candles per request. "
            "This is not a historical data cutoff in the private/full engine.")
    bars = synthetic(req)
    if len(bars) < 2:
        raise ValueError("Not enough candles")
    result = run_backtest(bars, create_strategy(strategy), risk, req.timeframe)
    from .chart import preview_candles
    result["candles_preview"] = preview_candles(bars, 900)
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
    assets = Path(__file__).resolve().parent / "static"
    modern = assets / "app" / "index.html"
    chosen = modern if modern.is_file() else assets / "index.html"
    return FileResponse(chosen, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


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


@app.get("/api/market/quote")
def market_quote(provider: str, symbol: str, exchange: str = "",
                 market_type: str = "swap"):
    """Authenticated last-trade/mid quote; independent of OHLCV candle close."""
    private_only()
    from .ticker import current_quote
    try:
        return current_quote(provider, exchange, symbol, market_type)
    except (ValueError, RuntimeError, ImportError) as exc:
        raise HTTPException(422,detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502,detail="Market quote provider is unavailable") from exc


@app.get("/api/markets")
def markets(provider: str, q: str, exchange: str = "",
            market_type: str = "swap", limit: int = 30):
    private_only()
    from .catalog import search_markets
    try:
        return search_markets(provider, q, exchange, market_type, limit)
    except (ValueError, ImportError, RuntimeError) as err:
        raise HTTPException(422, detail=str(err)) from err


@app.post("/api/strategies/generate")
async def generate_strategy_draft(payload: dict):
    """Server-side opt-in AI code generation; never auto-run or auto-save."""
    private_only()
    from .ai import generate_pine
    try:
        return await generate_pine(payload.get("description", ""))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        # Do not leak provider credentials or private server internals.
        raise HTTPException(502, "AI provider request failed") from exc


@app.get("/api/strategies")
def saved_strategies(limit: int = 100):
    private_only()
    from .library import list_strategies
    try:
        return list_strategies(Store(), limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/strategies")
def create_saved_strategy(payload: dict):
    private_only()
    from .library import save_strategy
    try:
        return save_strategy(Store(), payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/strategies/{strategy_id}")
def saved_strategy(strategy_id: str):
    private_only()
    from .library import get_strategy
    strategy = get_strategy(Store(), strategy_id)
    if strategy is None:
        raise HTTPException(404, "No such strategy")
    return strategy


@app.put("/api/strategies/{strategy_id}")
def update_saved_strategy(strategy_id: str, payload: dict):
    private_only()
    from .library import save_strategy
    try:
        return save_strategy(Store(), payload, strategy_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete("/api/strategies/{strategy_id}")
def delete_saved_strategy(strategy_id: str):
    private_only()
    from .library import delete_strategy
    if not delete_strategy(Store(), strategy_id):
        raise HTTPException(404, "No such strategy")
    return {"deleted": True, "id": strategy_id}


@app.get("/api/strategies/{strategy_id}/revisions")
def saved_strategy_revisions(strategy_id: str, limit: int = 100):
    private_only()
    from .library import revisions, get_strategy
    if get_strategy(Store(), strategy_id) is None:
        raise HTTPException(404, "No such strategy")
    try:
        return revisions(Store(), strategy_id, limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/strategies/{strategy_id}/restore/{revision}")
def restore_saved_strategy(strategy_id: str, revision: int):
    private_only()
    from .library import restore_revision
    try:
        return restore_revision(Store(), strategy_id, revision)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/portfolio/backtests")
def portfolio_backtest(payload: dict):
    """Synchronized cross-venue research: one shared simulated account."""
    private_only()
    from .portfolio import run_portfolio
    try:
        return run_portfolio(payload)
    except (ValueError,RuntimeError,PermissionError) as exc:
        raise HTTPException(422,detail=str(exc)) from exc


@app.post("/api/backtests/batch")
def backtests_batch(payload: dict):
    """Run common strategy independently across multiple exchanges/DEX venues."""
    private_only()
    from .batch import run_multi_market
    try:
        return run_multi_market(payload)
    except (ValueError, RuntimeError, PermissionError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


class CandleLoadPayload(BaseModel):
    data: dict = Field(default_factory=dict)
    refresh: bool = False
    max_points: int = 1500
    # Chart can page through the FULL cached dataset in exact native bars.
    # A display window is never passed into the strategy backtest engine.
    view_end_ms: int | None = None


@app.post("/api/candles/load")
def load_market_candles(payload: CandleLoadPayload):
    """Authenticated real OHLCV: backfill missing history + refresh live tail.

    Live, still-forming bars are displayed but NEVER persisted for backtests.
    Viewport is exact resolution; it is never mislabeled aggregated 15m/1m data.
    """
    private_only()
    from dataclasses import replace
    from .chart import read_candles
    from .live import sync_recent_candles, attach_latest_to_chart
    from .service import load_bars
    from .model import INTERVALS, iso_ms
    import time
    try:
        req = DataRequest(**payload.data)
        req.validate()
        if req.provider == "demo":
            raise ValueError("Production chart requires real market data, not demo")
        if req.provider not in ("ccxt", "hyperliquid", "yfinance", "csv"):
            raise ValueError("Unsupported chart provider")
        if not 10 <= payload.max_points <= 5000:
            raise ValueError("max_points must be 10..5000 for display only")
        start_ms,end_ms = iso_ms(req.start),iso_ms(req.end)
        now = int(time.time()*1000)
        step = INTERVALS[req.timeframe]
        window_end = min(end_ms, now + step)
        if payload.view_end_ms is not None:
            if not start_ms < payload.view_end_ms <= end_ms:
                raise ValueError("view_end_ms is outside requested history")
            window_end = min(payload.view_end_ms, end_ms)
        window_start = max(start_ms, window_end - payload.max_points*step)
        viewport = replace(req, start=datetime.fromtimestamp(window_start/1000,timezone.utc).isoformat(),
                           end=datetime.fromtimestamp(window_end/1000,timezone.utc).isoformat())
        store = Store()
        summary = store.data_summary(viewport)
        # Real-time updates use an independent small tail request. First-time
        # history is fetched once; every subsequent poll avoids a full download.
        tolerance = 4*86400000 if req.provider == "yfinance" else 2*step
        has_gap_at_start = (summary["count"] >= 2 and
                            summary["first_ts"] is not None and
                            summary["first_ts"] > window_start + tolerance)
        has_gap_at_end = (summary["count"] >= 2 and
                          summary["last_ts"] is not None and
                          summary["last_ts"] + 3*step < min(window_end,now)
                          and req.provider != "csv")
        needs_history = (summary["count"] < 2 or has_gap_at_start or has_gap_at_end)
        warnings = []
        if needs_history or (payload.refresh and req.provider in ("csv","yfinance")):
            try:
                # Only backfill the visible range. Full history for backtests
                # remains independently available through /api/backtests.
                _, _, coverage_warnings = load_bars(
                    viewport, store, refresh=True, incremental=False)
                warnings.extend(coverage_warnings)
            except (ValueError, RuntimeError, TimeoutError, ImportError, OSError) as exc:
                if summary["count"] < 2:
                    raise
                warnings.append("History refresh failed; chart shows cached bars: " + str(exc))
        # Only the current (not paged) chart follows live ticks.
        following_live = (payload.view_end_ms is None and
                          start_ms <= now < end_ms and
                          req.provider in ("ccxt","hyperliquid"))
        snapshot = None
        if following_live:
            try:
                snapshot = sync_recent_candles(req, store, now_ms=now)
            except Exception as exc:
                warnings.append("Live update failed; prices are NOT current: " + str(exc)[:180])
        chart = read_candles(viewport, store, payload.max_points)
        if not chart["candles"] and not (snapshot and snapshot.get("partial")):
            raise ValueError("No market OHLCV returned for selected symbol/range")
        if snapshot:
            chart = attach_latest_to_chart(chart, snapshot)
        else:
            chart.update(live_supported=False, fetched_at_ms=None,
                         last_price_ts=None, partial_candle=False,
                         live_warning=("Historical range: live updates paused" if payload.view_end_ms is not None
                                       else "Stock/CSV source does not promise live prices"))
        # Metadata is explicit so users can compare the same exchange + timeframe.
        chart.update(provider=req.provider, exchange=req.exchange, symbol=req.symbol,
                     timeframe=req.timeframe, native_interval_ms=step,
                     view_start_ms=window_start, view_end_ms=window_end,
                     server_time_ms=now, time_zone="UTC",
                     warnings=warnings,
                     is_live=bool(following_live and snapshot and
                                  snapshot.get("last_price_ts") is not None and
                                  not snapshot.get("live_warning")),
                     price_type="trade OHLCV (not mark or index price)",
                     exact_timeframe=chart["bucket_ms"] == step)
        if not chart["exact_timeframe"]:
            warnings.append("Chart candles are aggregated; expand/shorten the visible interval to compare native candles")
        return chart
    except (ValueError, RuntimeError, TimeoutError, ImportError, OSError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except Exception as exc:
        # Errors are reported clearly, not silently substituted with demo prices.
        venue = str(payload.data.get("exchange") or payload.data.get("provider") or "market")
        raise HTTPException(502, detail=f"{venue} market request failed ({type(exc).__name__}): {str(exc)[:200]}") from exc


@app.get("/api/candles")
def candles(provider: str, symbol: str, start: str, end: str,
            timeframe: str = "1d", exchange: str = "", market_type: str = "swap",
            max_points: int = 1200, include_funding: bool = False):
    """Query downsampled K lines for chart display only."""
    private_only()
    from .chart import read_candles
    try:
        req = DataRequest(provider=provider, exchange=exchange, symbol=symbol,
                          timeframe=timeframe, start=start, end=end,
                          market_type=market_type, include_funding=include_funding)
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
