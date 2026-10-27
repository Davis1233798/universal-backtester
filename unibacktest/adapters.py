"""Adapters return sorted canonical UTC Bars. All dates are [start, end)."""
from __future__ import annotations
import csv
import hashlib
import importlib
import math
import random
import time
from datetime import datetime, timezone, time as dt_time
from pathlib import Path
import httpx
from .model import Bar, DataRequest, INTERVALS, iso_ms, normalize


class CoverageError(RuntimeError):
    pass


def _requested(req: DataRequest, bars: list[Bar]) -> list[Bar]:
    s, e = iso_ms(req.start), iso_ms(req.end)
    return normalize([b for b in bars if s <= b.ts < e])


def synthetic(req: DataRequest) -> list[Bar]:
    """Deterministic SAMPLE ONLY. Never use this as proof of live-market performance."""
    step = INTERVALS[req.timeframe]
    s, e = iso_ms(req.start), iso_ms(req.end)
    if (e - s) // step > 100_000:
        raise ValueError("demo limited to 100k candles")
    seed = int(hashlib.sha256(req.cache_key().encode()).hexdigest()[:15], 16)
    rng = random.Random(seed)
    price = 100.0
    out = []
    for i, ts in enumerate(range(s - (s % step), e, step)):
        drift = .00008 + .003 * math.sin(i/90.0)
        growth = max(.5, 1 + drift + rng.gauss(0, .009))
        op = price
        price *= growth
        high = max(op, price) * (1 + rng.random() * .005)
        low = min(op, price) * (1 - rng.random() * .005)
        if ts >= s:
            out.append(Bar(ts, op, high, low, price, 10 + rng.random()*100))
    return out


def from_csv(req: DataRequest) -> list[Bar]:
    path = Path(req.csv_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"CSV not found: {path}")
    out = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            t = row.get("ts") or row.get("timestamp") or row.get("date")
            if not t:
                raise ValueError("CSV requires ts, timestamp, or date field")
            if isinstance(t, str) and t.isdecimal():
                ts = int(t)
                if ts < 1_000_000_000_000:
                    ts *= 1000  # UNIX seconds
            else:
                ts = iso_ms(t)
            out.append(Bar(ts, float(row["open"]), float(row["high"]),
                           float(row["low"]), float(row["close"]), float(row.get("volume") or 0),
                           float(row.get("funding_rate") or 0)))
    return _requested(req, out)


def _apply_funding(bars: list[Bar], events: list[tuple[int, float]], timeframe: str) -> list[Bar]:
    """Map settlement timestamps to the candle ending at settlement (not future bars).
    For coarse timeframes, sum several funding payments; price drift within interval
    is ignored, so funding P&L is approximate.
    """
    step = INTERVALS[timeframe]
    charges: dict[int, float] = {}
    for ts, rate in events:
        candle_ts = ((ts - 1) // step) * step
        charges[candle_ts] = charges.get(candle_ts, 0.0) + rate
    return [Bar(b.ts,b.open,b.high,b.low,b.close,b.volume,charges.get(b.ts,0.0)) for b in bars]


def _ccxt_funding(exchange, req: DataRequest) -> list[tuple[int, float]]:
    if not exchange.has.get("fetchFundingRateHistory"):
        raise CoverageError(f"{req.exchange}: historical funding API unavailable. Use CSV funding_rate.")
    events: dict[int,float] = {}
    since, end = iso_ms(req.start), iso_ms(req.end)
    while since < end:
        page = exchange.fetch_funding_rate_history(req.symbol, since=since, limit=1000)
        if not page:
            break
        for event in page:
            ts = int(event["timestamp"])
            if since <= ts <= end:
                events[ts] = float(event["fundingRate"])
        nxt = int(page[-1]["timestamp"])+1
        if nxt <= since:
            raise RuntimeError("funding rate pagination stalled")
        since = nxt

    if not events:
        raise CoverageError("No historical funding returned; check API range and exchange limitations")
    return sorted(events.items())


def _hyperliquid_funding(client: httpx.Client, req: DataRequest, coin: str) -> list[tuple[int,float]]:
    since, end = iso_ms(req.start), iso_ms(req.end)
    events: dict[int,float] = {}
    while since < end:
        response = client.post("https://api.hyperliquid.xyz/info", json={
            "type":"fundingHistory", "coin":coin, "startTime":since, "endTime":end})
        response.raise_for_status()
        page = response.json()
        if not isinstance(page,list):
            raise RuntimeError("Unexpected Hyperliquid funding format")
        if not page:
            break
        for r in page:
            ts = int(r["time"])
            if since <= ts <= end:
                events[ts] = float(r["fundingRate"])
        nxt = int(page[-1]["time"])+1
        if nxt <= since:
            raise RuntimeError("Hyperliquid funding pagination stalled")
        since = nxt

    if not events:
        raise CoverageError("No historical Hyperliquid funding returned")
    return sorted(events.items())


def from_ccxt(req: DataRequest) -> list[Bar]:
    try:
        import ccxt
    except ImportError as err:
        raise RuntimeError("Install: pip install -e '.[cex]'") from err
    if req.exchange not in ccxt.exchanges:
        raise ValueError(f"Unknown CCXT exchange: {req.exchange}")
    exchange = getattr(ccxt, req.exchange)({"enableRateLimit": True,
        "timeout": 20000, "options": {"defaultType": req.market_type}})
    try:
        exchange.load_markets()
        if not exchange.has.get("fetchOHLCV"):
            raise ValueError(f"{req.exchange} has no public fetchOHLCV")
        if req.symbol not in exchange.markets:
            raise ValueError(f"Symbol not listed: {req.symbol} on {req.exchange}")
        if req.timeframe not in exchange.timeframes:
            raise ValueError(f"{req.timeframe} unavailable on {req.exchange}")
        start, end = iso_ms(req.start), iso_ms(req.end)
        since, step = start, INTERVALS[req.timeframe]
        out: list[Bar] = []
        while since < end:
            page = exchange.fetch_ohlcv(req.symbol, req.timeframe, since=since, limit=1000)
            if not page:
                break
            for a in page:
                if start <= int(a[0]) < end:
                    out.append(Bar(int(a[0]), *[float(x) for x in a[1:6]]))
            next_since = int(page[-1][0]) + step
            if next_since <= since:
                raise RuntimeError("CCXT pagination stalled")
            since = next_since
            if len(page) < 2 and since < end:
                # Some endpoints return one candle per request; can still advance.
                continue

        if req.include_funding:
            out = _apply_funding(out, _ccxt_funding(exchange,req), req.timeframe)
        return _requested(req, out)
    finally:
        if hasattr(exchange, "close"):
            exchange.close()


def from_hyperliquid(req: DataRequest) -> list[Bar]:
    intervals = {"1m","3m","5m","15m","30m","1h","2h","4h","8h","12h","1d","3d","1w"}
    if req.timeframe not in intervals:
        raise ValueError("Hyperliquid does not support requested timeframe")
    # Spot / perp require different coin identifiers; this adapter targets perps.
    coin = req.symbol.split("/")[0]
    if ":" in req.symbol and "/" not in req.symbol:
        coin = req.symbol  # HIP-3 symbols e.g. xyz:XYZ100
    start, end = iso_ms(req.start), iso_ms(req.end)
    step = INTERVALS[req.timeframe]
    if (end - start) // step > 4999:
        raise CoverageError("Hyperliquid snapshot has a 5000-candle rolling limit. "
                            "Request <=4999 bars or import archived data via CSV.")
    with httpx.Client(timeout=30) as client:
        response = client.post("https://api.hyperliquid.xyz/info", json={"type": "candleSnapshot",
            "req": {"coin": coin, "interval": req.timeframe, "startTime": start, "endTime": end}})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError(f"Hyperliquid returned unexpected response: {str(data)[:200]}")
        out = [Bar(int(b["t"]), float(b["o"]), float(b["h"]),
              float(b["l"]), float(b["c"]), float(b["v"])) for b in data]
        if req.include_funding:
            out = _apply_funding(out, _hyperliquid_funding(client, req, coin), req.timeframe)
    return _requested(req, out)


def from_yfinance(req: DataRequest) -> list[Bar]:
    if req.timeframe not in ("1m", "5m", "15m", "30m", "1h", "1d", "1w"):
        raise ValueError("Timeframe not supported by Yahoo/yfinance adapter")
    try:
        import yfinance as yf
    except ImportError as err:
        raise RuntimeError("Install: pip install -e '.[stocks]'") from err
    interval = "60m" if req.timeframe == "1h" else req.timeframe
    # Raw OHLC is required when comparing the chart with the actual venue.
    # Adjusted OHLC differs around dividends/splits and must NOT be silently
    # represented as the market's execution price.
    frame = yf.Ticker(req.symbol).history(start=req.start[:10], end=req.end[:10],
                                            interval=interval, auto_adjust=False, actions=False)
    if frame.empty:
        return []
    out = []
    for t, r in frame.iterrows():
        # Daily/weekly equities are keyed to exchange-local SESSION DATE rather
        # than actual UTC midnight (which could be the previous calendar day).
        # For intraday candles retain actual UTC timestamps.
        ts = (int(datetime.combine(t.date(), dt_time.min, tzinfo=timezone.utc).timestamp()*1000)
              if req.timeframe in ("1d", "1w") else int(t.timestamp()*1000))
        out.append(Bar(ts, float(r["Open"]), float(r["High"]),
                       float(r["Low"]), float(r["Close"]), float(r["Volume"])))
    return _requested(req, out)


PROVIDERS = {"demo": synthetic, "csv": from_csv, "ccxt": from_ccxt,
             "hyperliquid": from_hyperliquid, "yfinance": from_yfinance}


def fetch(req: DataRequest) -> list[Bar]:
    req.validate()
    if req.provider.startswith("plugin:"):
        module = importlib.import_module(req.provider[len("plugin:"):])
        result = module.fetch(req)
        if not isinstance(result, list) or not all(isinstance(x, Bar) for x in result):
            raise TypeError("External adapter must return list[Bar]")
        return _requested(req, result)
    return PROVIDERS[req.provider](req)
