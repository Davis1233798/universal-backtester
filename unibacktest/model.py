"""Canonical UTC candles and validated risk configuration."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
import os
from typing import Any


def iso_ms(s: str | int | float | None) -> int:
    if isinstance(s, (int, float)):
        return int(s)
    if not s:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


INTERVALS = {"1m": 60000, "3m": 180000, "5m": 300000, "15m": 900000,
             "30m": 1800000, "1h": 3600000, "2h": 7200000, "4h": 14400000,
             "8h": 28800000, "12h": 43200000, "1d": 86400000, "3d": 259200000,
             "1w": 604800000}


@dataclass(frozen=True)
class Bar:
    ts: int                    # UTC milliseconds, candle open
    open: float
    high: float
    low: float
    close: float
    volume: float
    funding_rate: float = 0.0  # only applied to derivative positions; due within this bar

    def __post_init__(self):
        values = (self.open, self.high, self.low, self.close, self.volume, self.funding_rate)
        if not all(isfinite(v) for v in values):
            raise ValueError(f"non-finite candle at {self.ts}")
        if self.low <= 0 or self.high < self.low or self.open <= 0 or self.close <= 0:
            raise ValueError(f"invalid OHLC at {self.ts}")
        if not self.low <= self.open <= self.high or not self.low <= self.close <= self.high:
            raise ValueError(f"open/close outside high-low at {self.ts}")
        if self.volume < 0:
            raise ValueError(f"negative volume at {self.ts}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize(bars: list[Bar]) -> list[Bar]:
    unique = {bar.ts: bar for bar in bars}
    return sorted(unique.values(), key=lambda x: x.ts)


@dataclass
class Risk:
    initial_cash: float = 10000.0
    fee_bps: float = 6.0
    slippage_bps: float = 2.0
    leverage: float = 1.0
    maintenance_margin_ratio: float = 0.005
    product_type: str = "perp"      # perp, future, spot, equity
    market: str = "crypto"           # crypto, stock
    force_close: bool = True
    r_reference_stop_pct: float | None = None  # Reporting-only risk reference, not an order

    def validate(self):
        if self.r_reference_stop_pct is not None and (not isfinite(self.r_reference_stop_pct) or not 0 < self.r_reference_stop_pct <= 100):
            raise ValueError('r_reference_stop_pct must be in (0, 100] or omitted')
        if self.initial_cash <= 0 or self.leverage < 1 or self.leverage > 125:
            raise ValueError("initial_cash must be positive; leverage must be in [1, 125]")
        if not (0 <= self.fee_bps <= 1000 and 0 <= self.slippage_bps <= 1000):
            raise ValueError("fee_bps/slippage_bps must be in [0, 1000]")
        if not 0 <= self.maintenance_margin_ratio < 1:
            raise ValueError("invalid maintenance_margin_ratio")
        if self.product_type not in ("perp", "future", "spot", "equity"):
            raise ValueError("unsupported product_type")
        if self.market not in ("crypto", "stock"):
            raise ValueError("unsupported market")
        if self.product_type in ("spot", "equity") and self.leverage != 1:
            raise ValueError("spot/equity leverage is 1 in this engine")


@dataclass
class DataRequest:
    provider: str = "demo"
    exchange: str = ""
    symbol: str = "BTC/USDT:USDT"
    timeframe: str = "1d"
    start: str = "2024-01-01"
    end: str = "2024-12-31"
    csv_path: str = ""
    market_type: str = "swap"
    allow_partial: bool = False
    include_funding: bool = False

    def validate(self):
        if self.timeframe not in INTERVALS:
            raise ValueError("unsupported timeframe")
        if iso_ms(self.start) >= iso_ms(self.end):
            raise ValueError("start must be strictly earlier than end")
        if self.provider.startswith("plugin:"):
            if os.environ.get("UBT_ALLOW_EXEC") != "1":
                raise PermissionError("Custom adapters require UBT_ALLOW_EXEC=1 on trusted host")
        elif self.provider not in ("demo", "csv", "ccxt", "hyperliquid", "yfinance"):
            raise ValueError(f"unsupported provider {self.provider}")
        if self.include_funding and self.provider not in ("ccxt", "hyperliquid"):
            raise ValueError("include_funding supported for CCXT / Hyperliquid only; CSV may carry funding_rate column")
        if self.provider == "ccxt" and not self.exchange:
            raise ValueError("CCXT requires an exchange ID")
        if self.provider == "csv" and not self.csv_path:
            raise ValueError("csv_path required")

    def cache_key(self) -> str:
        # Include source details to prevent BTC spot/perp or exchange mixups.
        return "|".join([self.provider, self.exchange, self.symbol, self.timeframe,
                         self.market_type, self.csv_path, "funding" if self.include_funding else "no_funding"])
