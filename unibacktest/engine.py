"""Close-signal / next-open fills; single-asset, linear USDT-like P&L model."""
from __future__ import annotations
import math
from dataclasses import asdict
from collections.abc import Sequence
from .model import Bar, Risk, INTERVALS, normalize


class _HistoricalBars(Sequence):
    """O(1) read-only as-of history view; no materialization of prior bars."""
    def __init__(self, bars: list[Bar], end: int):
        self._bars, self._end = bars, end

    def __len__(self):
        return self._end

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self._bars[i].to_dict() for i in range(*index.indices(self._end))]
        if not isinstance(index, int):
            raise TypeError("bar index must be int or slice")
        if index < 0:
            index += self._end
        if index < 0 or index >= self._end:
            raise IndexError(index)
        return self._bars[index].to_dict()


def _metrics(equity: list[dict], closed: list[dict], fees: float, funding: float,
             risk: Risk, timeframe: str) -> dict:
    """Closed trades use NET P&L; partial exits count as individual closed slices.
    R needs an explicit reporting reference stop distance, NOT an active stop.
    """
    values = [x["equity"] for x in equity]
    if not values:
        raise ValueError("empty equity")
    peak = values[0]
    dd, dd_money = 0.0, 0.0
    for x in values:
        peak = max(peak, x)
        if peak > 0:
            dd = max(dd, (peak - x)/peak)
        dd_money = max(dd_money, peak-x)
    gains = [values[i]/values[i-1]-1 for i in range(1, len(values)) if values[i-1] > 0]
    trading_days = 252 if risk.market == "stock" else 365
    if timeframe in ("1d", "3d", "1w"):
        period_year = {"1d": trading_days, "3d": trading_days/3, "1w": 52}[timeframe]
    else:
        days = 6.5 if risk.market == "stock" else 24
        period_year = trading_days * days * 3600000/INTERVALS[timeframe]
    sharpe, sortino, vol = None, None, None
    if len(gains) >= 2:
        avg = sum(gains)/len(gains)
        std = math.sqrt(sum((r-avg)**2 for r in gains)/(len(gains)-1))
        if std > 0:
            sharpe = avg/std * math.sqrt(period_year)
            vol = std*math.sqrt(period_year)*100
        downside = math.sqrt(sum(min(0, r)**2 for r in gains)/len(gains))
        if downside > 0:
            sortino = avg/downside * math.sqrt(period_year)
    years = max((equity[-1]["ts"] - equity[0]["ts"])/(365.25*86400000), 0)
    initial, last = risk.initial_cash, values[-1]
    cagr = ((last/initial)**(1/years)-1) if years > 0 and last > 0 else None
    pnls = [x["net_pnl"] for x in closed]
    winners = [x for x in pnls if x > 0]
    losers = [x for x in pnls if x < 0]
    total_profit, total_loss = sum(winners), -sum(losers)
    pf = total_profit/total_loss if total_loss > 0 else None
    if not pnls:
        pf_status = "no_closed_trades"
    elif not losers:
        pf_status = "no_losses" if winners else "no_wins_or_losses"
    else:
        pf_status = "calculated"
    avg_win = total_profit/len(winners) if winners else None
    avg_loss = total_loss/len(losers) if losers else None
    rs = [x["r_multiple"] for x in closed if x["r_multiple"] is not None]
    exposure = sum(abs(x.get("position", 0)) > 1e-12 for x in equity)/len(equity)
    win_streak = loss_streak = max_wins = max_losses = 0
    for pnl in pnls:
        win_streak = win_streak+1 if pnl > 0 else 0
        loss_streak = loss_streak+1 if pnl < 0 else 0
        max_wins = max(max_wins, win_streak)
        max_losses = max(max_losses, loss_streak)
    def rounded(x):
        return round(x, 6) if x is not None and math.isfinite(x) else None
    return {"initial_equity": initial, "final_equity": rounded(last),
            "net_profit": rounded(last-initial),
            "return_pct": round((last/initial-1)*100, 4),
            "cagr_pct": round(cagr*100, 4) if cagr is not None else None,
            "max_drawdown_pct": round(dd*100, 4),
            "max_drawdown_amount": rounded(dd_money),
            "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "sortino": rounded(sortino), "annual_volatility_pct": rounded(vol),
            "calmar": rounded(cagr/dd) if cagr is not None and dd > 0 else None,
            "exposure_pct": round(exposure*100, 4),
            "closed_trades": len(closed),
            "winning_trades": len(winners), "losing_trades": len(losers),
            "breakeven_trades": len(closed)-len(winners)-len(losers),
            "win_rate_pct": round(len(winners)/len(closed)*100, 4) if closed else None,
            "profit_factor": rounded(pf), "profit_factor_status": pf_status,
            "gross_profit_net": rounded(total_profit), "gross_loss_net_abs": rounded(total_loss),
            "average_trade_net": rounded(sum(pnls)/len(pnls)) if pnls else None,
            "average_win_net": rounded(avg_win), "average_loss_net_abs": rounded(avg_loss),
            "payoff_ratio": rounded(avg_win/avg_loss) if avg_win is not None and avg_loss else None,
            "largest_win_net": rounded(max(winners)) if winners else None,
            "largest_loss_net": rounded(min(losers)) if losers else None,
            "max_consecutive_wins": max_wins, "max_consecutive_losses": max_losses,
            "recovery_factor": rounded((last-initial)/dd_money) if dd_money > 0 else None,
            "average_r": rounded(sum(rs)/len(rs)) if rs else None,
            "r_trades": len(rs), "r_reference_stop_pct": risk.r_reference_stop_pct,
            "fees_paid": rounded(fees), "funding_paid_net": rounded(funding)}


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
    entry_ts = None
    open_entry_fees = 0.0
    open_funding = 0.0
    wallet = risk.initial_cash
    total_fees = 0.0
    total_funding = 0.0
    pending_target: float | None = None
    protective_exit: dict | None = None
    live_target = 0.0
    recent = []
    fills: list[dict] = []
    closed: list[dict] = []
    equity: list[dict] = []
    liquidations = 0
    stopped_out = False

    def equity_at(price: float) -> float:
        return wallet + position * (price - entry)

    def fill(ts: int, price: float, delta: float, why: str, *, slip_bps: float | None = None):
        nonlocal wallet, position, entry, entry_ts, total_fees
        nonlocal open_entry_fees, open_funding
        if abs(delta) < 1e-12:
            return
        applied_slip = risk.slippage_bps if slip_bps is None else slip_bps
        fill_price = price * (1 + math.copysign(applied_slip / 10000, delta))
        fee = abs(delta * fill_price) * risk.fee_bps/10000
        old = position
        closing = min(abs(old), abs(delta)) if old * delta < 0 else 0.0
        close_fee = fee * closing / abs(delta) if closing else 0.0
        if closing:
            fraction = closing/abs(old)
            pnl = math.copysign(closing, old) * (fill_price-entry)
            entry_fee_share = open_entry_fees*fraction
            funding_share = open_funding*fraction
            net = pnl - entry_fee_share - close_fee - funding_share
            risk_amount = (closing * entry * risk.r_reference_stop_pct/100
                           if risk.r_reference_stop_pct is not None else None)
            closed.append({"ts": ts, "entry_ts": entry_ts, "entry_price": round(entry, 8),
                           "exit_price": round(fill_price, 8),
                           "qty": round(math.copysign(closing, old), 8),
                           "gross_pnl": round(pnl, 8),
                           "entry_fee": round(entry_fee_share, 8),
                           "exit_fee": round(close_fee, 8),
                           "funding_paid_net": round(funding_share, 8),
                           "net_pnl": round(net, 8),
                           "initial_risk": round(risk_amount, 8) if risk_amount else None,
                           "r_multiple": round(net/risk_amount, 8) if risk_amount else None,
                           "reason": why})
            wallet += pnl
            open_entry_fees -= entry_fee_share
            open_funding -= funding_share
        wallet -= fee
        total_fees += fee
        new = old + delta
        if abs(new) < 1e-12:
            new, entry, entry_ts = 0.0, 0.0, None
            open_entry_fees = open_funding = 0.0
        elif old == 0 or old*new < 0:
            entry, entry_ts = fill_price, ts
            open_entry_fees = fee-close_fee
            open_funding = 0.0
        elif abs(new) > abs(old) and old*delta > 0:
            entry = (abs(old)*entry + abs(delta)*fill_price)/abs(new)
            open_entry_fees += fee
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

            # Execute prior-close protective orders during this bar, after
            # the next-open signal fill. If both bounds are touched, assume
            # the stop happened first: OHLC has no intra-bar chronology.
            if position and protective_exit:
                stop=protective_exit.get("stop")
                limit=protective_exit.get("limit")
                long=position>0
                stop_hit=(stop is not None and
                          (b.low<=stop if long else b.high>=stop))
                limit_hit=(limit is not None and
                           (b.high>=limit if long else b.low<=limit))
                if stop_hit or limit_hit:
                    # A gap through the stop executes at the worse open.
                    # Favorable gap through a limit fills at the open, without
                    # charging adverse slippage on the passive limit fill.
                    if stop_hit:
                        execution=(min(b.open,stop) if long
                                   else max(b.open,stop))
                        fill(b.ts,execution,-position,"stop_market")
                    else:
                        execution=(max(b.open,limit) if long
                                   else min(b.open,limit))
                        fill(b.ts,execution,-position,"take_profit_limit",slip_bps=0)
                    live_target=0.0
                    pending_target=None
                    protective_exit=None

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
                open_funding += payment

            current_equity = equity_at(b.close)
            equity.append({"ts": b.ts, "equity": round(current_equity, 8),
                           "position": round(position, 8), "close": b.close})
            recent.append(b.to_dict())
            if len(recent) > window:
                recent.pop(0)
            if i == len(bars)-1 or stopped_out:
                continue
            context_bars = (_HistoricalBars(bars, i+1)
                            if getattr(strategy, "history_all", False) else list(recent))
            ctx = {"bars": context_bars, "target": live_target, "position": position,
                   "wallet": wallet, "equity": current_equity, "timeframe": timeframe}
            target = float(strategy(ctx))
            event = getattr(strategy, "order_event", None)
            if isinstance(event, dict):
                if event.get("cancel"):
                    protective_exit = None
                else:
                    protective_exit = dict(event)
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
                    "Sharpe/Sortino annualization approximates trading hours; no risk-free-rate adjustment.",
                    "Profit factor, win rate and average trade use realized NET P&L after allocated fees and funding; partial exits count as separate trades.",
                    "Protective stop-market and take-profit limit are activated on the next candle. A gap through a stop fills at its worse open; concurrent OHLC hits assume the stop first.",
                    "No order book, partial fills, trailing/stop-limit orders, tick/lot-size constraints or exchange-specific liquidation tiers.",
                    "R requires r_reference_stop_pct as a reporting denominator only; order stops do not automatically define 1R."]}
    finally:
        if hasattr(strategy, "close"):
            strategy.close()
