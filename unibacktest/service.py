"""Reusable data refresh, backtest orchestration and run persistence."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from .adapters import fetch
from .engine import run_backtest
from .model import DataRequest, Risk, INTERVALS, iso_ms
from .storage import Store
from .strategies import create_strategy


def prepare(config: dict) -> tuple[DataRequest, Risk]:
    req = DataRequest(**config.get("data", {}))
    risk = Risk(**config.get("risk", {}))
    req.validate()
    risk.validate()
    if req.provider == "yfinance" and risk.market != "stock":
        raise ValueError("yfinance requires market=stock")
    if req.provider == "hyperliquid" and risk.product_type != "perp":
        raise ValueError("Hyperliquid adapter provides perpetual OHLCV here")
    if req.include_funding and risk.product_type != "perp":
        raise ValueError("include_funding requires a perpetual contract in this engine")
    return req, risk


def load_bars(req: DataRequest, store: Store, refresh: bool = False,
              incremental: bool = False):
    existing = store.get_bars(req)
    fetched = 0
    if refresh or not existing or incremental:
        fetch_req = DataRequest(**asdict(req))
        if incremental and existing and req.provider not in ("csv", "demo"):
            # Re-fetch the most recent candles to account for revisions/late reports.
            since = max(iso_ms(req.start), existing[-1].ts - 2*INTERVALS[req.timeframe])
            fetch_req.start = datetime.fromtimestamp(since/1000, tz=timezone.utc).isoformat()
        new = fetch(fetch_req)
        # Last open candle may still be forming; only accept complete intervals.
        now = int(datetime.now(timezone.utc).timestamp()*1000)
        new = [b for b in new if b.ts + INTERVALS[req.timeframe] <= now]
        fetched = store.upsert_bars(req.cache_key(), new)
    bars = store.get_bars(req)
    if len(bars) < 2:
        raise ValueError("Not enough historical candles. Check market, symbol, date range and data-provider limits.")
    coverage = {"first_ts": bars[0].ts, "last_ts": bars[-1].ts,
                "first_requested_ts": iso_ms(req.start), "end_exclusive_ts": iso_ms(req.end),
                "cached_bars": len(bars), "newly_fetched_bars": fetched}
    warnings = []
    if bars[0].ts > iso_ms(req.start) + 2*INTERVALS[req.timeframe]:
        warnings.append("Historical data starts later than requested (listing date, holiday or provider restriction).")
    # Avoid warning for weekends / holidays of stock exchanges.
    if req.provider not in ("yfinance",) and bars[-1].ts + 3*INTERVALS[req.timeframe] < min(iso_ms(req.end), int(datetime.now(timezone.utc).timestamp()*1000)):
        warnings.append("Historical data ends earlier than requested; coverage may be incomplete.")
    gaps = sum(b.ts - a.ts > (3 if req.provider == "yfinance" else 1.5)*INTERVALS[req.timeframe]
               for a,b in zip(bars, bars[1:]))
    if gaps:
        warnings.append(f"Detected {gaps} intervals with missing candles or nontrading days; no forward fill was applied.")
    return bars, coverage, warnings


def execute(config: dict, store: Store | None = None, save: bool = True,
            incremental: bool = False) -> dict:
    store = store or Store()
    req, risk = prepare(config)
    strat = create_strategy(config.get("strategy", {"type":"builtin","name":"sma_cross"}))
    streaming = bool(config.get("streaming",False))
    if streaming:
        if getattr(strat,"streaming_window",500) is None:
            raise ValueError("Pine streaming requires fixed/input lookbacks; use full-history mode for dynamic lengths")
        # Always prefer cached, cursor-backed input. Initial provider download
        # is still materialized by the adapter; large ingestion needs a separate
        # checkpointed importer and/or Parquet adapter.
        summary=store.data_summary(req)
        fetched=0
        if not summary["count"] or config.get("refresh") or incremental:
            incoming=fetch(req)
            now=int(datetime.now(timezone.utc).timestamp()*1000)
            incoming=[b for b in incoming if b.ts+INTERVALS[req.timeframe]<=now]
            fetched=store.upsert_bars(req.cache_key(),incoming)
            summary=store.data_summary(req)
        if summary["count"]<2:
            raise ValueError("Not enough historical bars")
        coverage={**summary,"newly_fetched_bars":fetched,
                  "cached_bars":summary["count"],"streaming_from_sqlite":True}
        warnings=[]
        bars=store.iter_bars(req)
    else:
        bars, coverage, warnings = load_bars(req, store, bool(config.get("refresh", False)), incremental)
    result = run_backtest(bars, strat, risk, req.timeframe, streaming=streaming)
    if risk.product_type == "perp" and result["funding_data_points"] == 0:
        warnings.append("NO HISTORICAL FUNDING: rate assumed zero! Import funding_rate via CSV for credible perpetual P&L.")
    if risk.product_type == "equity":
        warnings.append("For yfinance, historical prices are adjusted research data; dividends, splits and delisted securities are not independently simulated.")
    result["coverage"] = coverage
    result["warnings"] = warnings
    if save:
        result["run_id"] = store.save_run(config, result)
    return result
