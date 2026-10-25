"""Bounded multi-venue fan-out: independent accounting per exchange/market.

This is a functional multiprocessing baseline, not the future Rust cluster engine.
No implicit cross-exchange netting, fills or shared balance is attempted.
"""
from __future__ import annotations

import math
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from .service import execute


def decimate_extrema(points: list[dict], max_points: int = 1200) -> list[dict]:
    """Downsample an equity series without inventing prices or hiding extremes.

    Keeps first/last and min/max in each time-ordered bucket. Metrics are always
    evaluated on the full-resolution equity curve BEFORE decimation.
    """
    if max_points < 4:
        raise ValueError("max_points must be >= 4")
    if len(points) <= max_points:
        return points
    interior = points[1:-1]
    buckets = (max_points - 2) // 2
    size = math.ceil(len(interior) / buckets)
    result = [points[0]]
    for start in range(0, len(interior), size):
        group = interior[start:start+size]
        lo = min(range(len(group)), key=lambda i: group[i]["equity"])
        hi = max(range(len(group)), key=lambda i: group[i]["equity"])
        for idx in sorted(set((lo, hi))):
            result.append(group[idx])
    result.append(points[-1])
    return result


def _one(index: int, config: dict, chart_points: int) -> dict:
    """Worker process creates its own storage and returns summary, not raw millions."""
    try:
        # Independent strategy instance and isolated P&L for each market.
        result = execute(config, save=False)
        equity = result.pop("equity")
        fills = result.pop("fills")
        trades = result.pop("closed_trades")
        result["equity_preview"] = decimate_extrema(equity, chart_points)
        result["fill_count"] = len(fills)
        result["closed_trade_count"] = len(trades)
        return {"index": index, "status": "success", "data": config["data"], "result": result}
    except (Exception) as exc:
        return {"index": index, "status": "error", "data": config.get("data", {}),
                "error": f"{type(exc).__name__}: {exc}"}


def run_multi_market(config: dict) -> dict:
    """Run one common strategy independently for every requested CEX/DEX venue.

    Venue-specific risk overrides may include fee_bps, slippage_bps, leverage,
    funding handling, or starting capital. A strategy is created per venue.
    This is not a synchronized cross-venue portfolio simulation.
    """
    markets = config.get("markets")
    if not isinstance(markets, list) or not markets:
        raise ValueError("markets must be a non-empty array")
    common_strategy = config.get("strategy", {"type": "builtin", "name": "sma_cross"})
    if not isinstance(common_strategy, dict):
        raise ValueError("strategy must be an object")
    risk_base = config.get("risk", {})
    if not isinstance(risk_base, dict):
        raise ValueError("risk must be an object")
    try:
        parallelism = int(config.get("workers", min(4, os.cpu_count() or 1)))
    except (ValueError, TypeError) as exc:
        raise ValueError("workers must be an integer") from exc
    if not (1 <= parallelism <= 32):
        raise ValueError("workers must be within 1..32 (bounded CPU workers)")
    chart_points = int(config.get("chart_points", 1200))
    if not 4 <= chart_points <= 5000:
        raise ValueError("chart_points must be within 4..5000; preview only")
    builds = []
    seen = set()
    for i, market in enumerate(markets):
        if not isinstance(market, dict):
            raise ValueError(f"markets[{i}] must be an object")
        data = market.get("data", {k:v for k,v in market.items() if k not in ("risk", "data")})
        if not isinstance(data, dict):
            raise ValueError(f"markets[{i}].data must be an object")
        risk = market.get("risk", {})
        if not isinstance(risk, dict):
            raise ValueError(f"markets[{i}].risk must be an object")
        identity = (data.get("provider"), data.get("exchange"), data.get("symbol"),
                    data.get("timeframe"), data.get("start"), data.get("end"),
                    data.get("market_type"), data.get("csv_path"))
        if identity in seen:
            raise ValueError(f"duplicate market identity: {identity!r}")
        seen.add(identity)
        builds.append({"data": data, "strategy": common_strategy,
                       "risk": {**risk_base, **risk}, "refresh": bool(config.get("refresh", False))})
    results: list[dict | None] = [None]*len(builds)
    # One process per worker, NOT one process per K line.
    # Failure of one venue should not drop all results.
    with ProcessPoolExecutor(max_workers=min(parallelism, len(builds)),
                             mp_context=multiprocessing.get_context("spawn")) as pool:
        pending = [pool.submit(_one, i, cfg, chart_points) for i,cfg in enumerate(builds)]
        for job in as_completed(pending):
            outcome = job.result()
            results[outcome["index"]] = outcome
    return {"count": len(results), "successful": sum(r["status"] == "success" for r in results),
            "failed": sum(r["status"] == "error" for r in results),
            "independent_accounting": True,
            "shared_liquidity_or_portfolio": False,
            "results": results}