"""Bounded real-market candle synchronization and honest chart coverage metadata.

The live/in-progress OHLCV is display-only. Never insert unfinished market bars
into the immutable historical dataset used by strategy backtests.
"""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
import time

from .adapters import fetch
from .model import DataRequest, INTERVALS, Bar, iso_ms
from .storage import Store


def _datetime_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def sync_recent_candles(req: DataRequest, store: Store, *, now_ms: int | None = None,
                        fetcher=None) -> dict:
    """Refresh only the last few market candles; return optional forming candle.

    Called after historical coverage is checked, before building the visible
    chart window. Caller handles upstream errors. The snapshot doesn't use
    the full historical start date, preventing costly full-range re-downloads.
    """
    now = int(time.time() * 1000) if now_ms is None else now_ms
    step = INTERVALS[req.timeframe]
    if req.provider not in ("ccxt", "hyperliquid") or not (
        iso_ms(req.start) <= now < iso_ms(req.end)
    ):
        return {"live_supported": False, "partial": None, "fetched_at_ms": None,
                "last_completed_ts": None, "last_price_ts": None,
                "live_warning": "此來源或時間區間不提供即時 K 線同步"}

    start = max(iso_ms(req.start), (now // step - 4) * step)
    end = min(iso_ms(req.end), (now // step + 1) * step)
    recent_req = replace(req, start=_datetime_utc(start),
                         end=_datetime_utc(end), include_funding=False)
    snapshot: list[Bar] = (fetcher or fetch)(recent_req)
    completed = sorted((b for b in snapshot if
                        iso_ms(req.start) <= b.ts < iso_ms(req.end)
                        and b.ts + step <= now), key=lambda b: b.ts)
    partials = sorted((b for b in snapshot if
                       iso_ms(req.start) <= b.ts <= now < b.ts + step
                       and b.ts < iso_ms(req.end)), key=lambda b: b.ts)

    # Funding-enabled caches have event rates. Do not overwrite them with
    # zero-funding snapshots. Incomplete bars MUST NEVER enter any history.
    if completed and not req.include_funding:
        store.upsert_bars(req.cache_key(), completed)
    partial = partials[-1].to_dict() if partials else None
    if partial is not None:
        partial.update(n_bars=1, last_ts=partial["ts"], is_partial=True)
    last_completed_ts = completed[-1].ts if completed else None
    price_ts = partial["ts"] if partial else last_completed_ts
    warning = None
    if price_ts is None:
        warning = "交易所未傳回最新 K 線，可能是商品未交易、API 限流或資料延遲"
    elif now - price_ts > 3 * step:
        warning = "最新行情距離目前時間超過三個 K 線週期，資料可能延遲"
    return {"live_supported": True, "partial": partial,
            "fetched_at_ms": now, "last_completed_ts": last_completed_ts,
            "last_price_ts": price_ts, "live_warning": warning}


def attach_latest_to_chart(chart: dict, snapshot: dict) -> dict:
    """Show the evolving last bar as a separate, clearly marked chart-only point."""
    candles = list(chart["candles"])
    partial = snapshot.get("partial")
    if partial is not None:
        candles = [b for b in candles if b["ts"] < partial["ts"]]
        candles.append(partial)
    return {**chart, "candles": candles, "display_points": len(candles),
            "live_supported": snapshot["live_supported"],
            "fetched_at_ms": snapshot["fetched_at_ms"],
            "last_completed_ts": snapshot["last_completed_ts"],
            "last_price_ts": snapshot["last_price_ts"],
            "live_warning": snapshot["live_warning"],
            "partial_candle": partial is not None}
