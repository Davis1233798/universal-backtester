"""Close-signal / next-open fills; single-asset, linear USDT-like P&L model."""
from __future__ import annotations
import math
from dataclasses import asdict
from .model import Bar, Risk, INTERVALS, normalize


def _metrics(equity: list[dict], closed: list[dict], fees: float, funding: float,
             risk: Risk, timeframe: str) -> dict:
    values = [x["equity"] for x in equity]
    if not values:
        raise ValueError("empty equity")
    peak = values[0]
    dd = 0.0
    for x in values:
        peak = max(peak, x)
        if peak > 0:
            dd = max(dd, (peak - x)/peak)
    gains = [values[i]/values[i-1]-1 for i in range(1, len(values)) if values[i-1] > 0]
    trading_days = 252 if risk.market == "stock" else 365
    if timeframe in ("1d", "3d", "1w"):
        period_year = {"1d": trading_days, "3d": trading_days/3, "1w": 52}[timeframe]
    else:
        days = 6.5 if risk.market == "stock" else 24
        period_year = trading_days * days * 3600000/INTERVALS[timeframe]
    sharpe = None
    if len(gains) >= 2:
        avg = sum(gains)/len(gains)
        std = math.sqrt(sum((r-avg)**2 for r in gains)/(len(gains)-1))
        if std > 0:
            sharpe = avg/std * math.sqrt(period_year)
    duration_year = max((equity[-1]["ts"] - equity[0]["ts"]) / (365.25*86400000), 0)
    initial = risk.initial_cash
    last = values[-1]
    cagr = ((last / initial)**(1/duration_year)-1) if duration_year > 0 and last > 0 else None
    return {"initial_equity": initial, "final_equity": round(last, 6),
            "return_pct": round((last/initial-1)*100, 4),
            "cagr_pct": round(cagr*100, 4) if cagr is not None else None,
            "max_drawdown_pct": round(dd*100, 4),
            "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "closed_trades": len(closed),
            "win_rate_pct": round(sum(x["gross_pnl"] > 0 for x in closed) / len(closed)*100, 4) if closed else None,
            "fees_paid": round(fees, 6), "funding_paid_net": round(funding, 6)}


def run_backtest(bars: list[Bar], strategy, risk: Risk, timeframe: str = "1d",
                 window: int = 500) -> dict:
    """Signals based on current bar CLOSE execute on next bar OPEN.

    Important limitations: 1 symbol; linear instrument only; cross-margin rough liquidation
    at bar low/high; no spreads, order-book impact, partial fills, dividends/borrow fees.
    Futures/perp historical funding must be attached explicitly per bar (CSV).
    """
    risk.validate()
    if timeframe not in INTERVALS:
        raise ValueError("unknown timeframe")
    bars = normalize(bars)
    if len(bars) < 2:
        raise ValueError("At least two bars required")
    position = 0.0
    entry = 0.0
    wallet = risk.initial_cash
    total_fees = 0.0
    total_funding = 0.0
    pending_target: float | None = None
    live_target = 0.0
    recent = []
    fills: list[dict] = []
    closed: list[dict] = []
    equity: list[dict] = []
    liquidations = 0
    stopped_out = False

    def equity_at(price: float) -> float:
        return wallet + position * (price - entry)

    def fill(ts: int, price: float, delta: float, why: str):
        nonlocal wallet, position, entry, total_fees
        if abs(delta) < 1e-12:
            return
        fill_price = price * (1 + math.copysign(risk.slippage_bps / 10000, delta))
        fee = abs(delta * fill_price) * risk.fee_bps/10000
        old = position
        if old and old*delta < 0:
            closing = min(abs(old), abs(delta))
            pnl = math.copysign(closing, old) * (fill_price-entry)
            wallet += pnl
            closed.append({"ts": ts, "gross_pnl": round(pnl, 8), "reason": why})
        wallet -= fee
        total_fees += fee
        new = old + delta
        if abs(new) < 1e-12:
            new, entry = 0.0, 0.0
        elif old == 0 or old*new < 0:
            entry = fill_price
        elif abs(new) > abs(old) and old*delta > 0:
            entry = (abs(old)*entry + abs(delta)*fill_price)/abs(new)
        position = new
        fills.append({"ts": ts, "price": round(fill_price, 8), "qty": round(delta, 8),
                      "fee": round(fee, 8), "reason": why, "position_after": round(position, 8)})

    try:
        for i, b in enumerate(bars):
            if pending_target is not None and not stopped_out:
                target = pending_target
                # No daily rebalance if the strategy kept the same desired signal.
                if abs(target-live_target) > 1e-10:
                    old_equity = max(0.0, equity_at(b.open))
                    goal_qty = target * risk.leverage * old_equity / b.open
                    fill(b.ts, b.open, goal_qty-position, "signal")
                    live_target = target
                pending_target = None

            # OHLC-only liquidation approximates an adverse movement at the extreme.
            if risk.product_type in ("perp", "future") and position:
                worst = b.low if position > 0 else b.high
                mm = abs(position) * worst * risk.maintenance_margin_ratio
                if equity_at(worst) <= mm:
                    fill(b.ts, worst, -position, "liquidation_extreme")
                    liquidations += 1
                    stopped_out = True
                    live_target = 0.0

            # Funding sign: positive funding paid by longs and received by shorts.
            if risk.product_type == "perp" and position and b.funding_rate:
                payment = position * b.close * b.funding_rate
                wallet -= payment
                total_funding += payment

            current_equity = equity_at(b.close)
            equity.append({"ts": b.ts, "equity": round(current_equity, 8),
                           "position": round(position, 8), "close": b.close})
            recent.append(b.to_dict())
            if len(recent) > window:
                recent.pop(0)
            if i == len(bars)-1 or stopped_out:
                continue
            ctx = {"bars": list(recent), "target": live_target, "position": position,
                   "wallet": wallet, "equity": current_equity, "timeframe": timeframe}
            target = float(strategy(ctx))
            if not math.isfinite(target) or not -1 <= target <= 1:
                raise ValueError("strategy target must be finite and in [-1, 1]")
            if risk.product_type in ("spot", "equity") and target < 0:
                raise ValueError("spot/equity strategy target cannot be negative")
            pending_target = target
        if risk.force_close and position:
            last = bars[-1]
            fill(last.ts + INTERVALS[timeframe], last.close, -position, "end_of_test")
            equity[-1]["equity"] = round(wallet, 8)
            equity[-1]["position"] = 0.0
        return {"metrics": _metrics(equity, closed, total_fees, total_funding, risk, timeframe),
                "equity": equity, "fills": fills, "closed_trades": closed,
                "liquidations": liquidations, "bars": len(bars),
                "funding_data_points": sum(b.funding_rate != 0 for b in bars),
                "assumptions": [
                    "Signals use completed-bar data; fills are NEXT candle open (except forced final close).",
                    "OHLC extreme liquidation is approximate; within-bar fill order is not modeled.",
                    "One linear-quoted instrument; spot/equity cannot short or lever.",
                    "Funding only charged for explicit nonzero funding_rate candle values; zero/missing are indistinguishable.",
                    "Equity uses close marks; one-position netting; no liquidity constraints, corporate-action cash flows or portfolio rebalancing.",
                    "Sharpe annualization approximates trading hours; no risk-free-rate adjustment."]}
    finally:
        if hasattr(strategy, "close"):
            strategy.close()
