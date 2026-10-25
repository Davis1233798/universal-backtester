"""Synchronized cross-venue portfolio research engine.

One shared simulated wallet. Native market fill, contract margin and chain gas
are NOT modeled; venues are assumed to quote the same currency and unit.
Signals at bar close fill on the NEXT common bar's open. Missing bar alignment
is an error, never silently forward filled.
"""
from __future__ import annotations

import importlib.util
import math
import os
from dataclasses import dataclass
from itertools import zip_longest
from .adapters import fetch
from .engine import _metrics, _OnlineEquity, _preview_append
from .model import DataRequest, Risk, INTERVALS
from .storage import Store

@dataclass
class _Book:
    name: str
    risk: Risk
    position: float = 0.0
    entry: float = 0.0
    entry_fees: float = 0.0
    funding: float = 0.0


def _strategy(config):
    kind=config.get("type","spread")
    if kind=="spread":
        enter=float(config.get("entry_bps",25))
        leave=float(config.get("exit_bps",5))
        if not all(map(math.isfinite,(enter,leave))) or not 0<=leave<enter:
            raise ValueError("Spread exit_bps must be nonnegative and less than entry_bps")
        def spread(ctx):
            quote=ctx["markets"]
            low=min(quote,key=lambda k:quote[k]["close"])
            high=max(quote,key=lambda k:quote[k]["close"])
            prices=[quote[x]["close"] for x in (low,high)]
            diff=(prices[1]-prices[0])*20000/sum(prices)
            if diff>=enter:
                return {key:(1 if key==low else -1 if key==high else 0) for key in quote}
            if diff<=leave:
                return {key:0 for key in quote}
            return ctx["targets"]
        return spread
    if kind=="python":
        if os.getenv("UBT_ALLOW_EXEC")!="1":
            raise PermissionError("Trusted custom Python requires UBT_ALLOW_EXEC=1")
        from pathlib import Path
        path=Path(config.get("path","")).resolve()
        if not path.is_file() or path.suffix!=".py":
            raise ValueError("Private strategy path must be an existing .py file")
        spec=importlib.util.spec_from_file_location("ubt_cross_venue_user",path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        callback=getattr(module,"on_venues",None)
        if not callable(callback):
            raise ValueError("Python cross-venue strategy must export on_venues(ctx)->dict")
        return callback
    raise ValueError("Cross-venue portfolio supports spread or trusted Python strategies")


def run_portfolio(config: dict, store: Store | None = None) -> dict:
    store=store or Store()
    items=config.get("venues")
    if not isinstance(items,list) or len(items)<2:
        raise ValueError("At least two venues required for shared-portfolio backtest")
    if len(items)>len(set((x.get("id") for x in items))):
        raise ValueError("Venue IDs must be unique")
    account=config.get("portfolio",{})
    initial=float(account.get("initial_cash",10000))
    gross_fraction=float(account.get("gross_notional_fraction",1))
    if not math.isfinite(initial) or initial<=0:
        raise ValueError("initial_cash must be finite and positive")
    if not math.isfinite(gross_fraction) or not 0<gross_fraction<=1:
        raise ValueError("gross_notional_fraction must be in (0,1]")
    clock=None
    books={}
    inputs=[]
    for i, raw in enumerate(items):
        if not isinstance(raw,dict):
            raise ValueError("Each venue must be an object")
        name=raw.get("id")
        if not isinstance(name,str) or not name or len(name)>64 or name in books:
            raise ValueError("Venue IDs must be unique, nonempty and <=64 characters")
        req=DataRequest(**raw.get("data",{}))
        req.validate()
        if clock is None:
            clock=(req.timeframe, req.start, req.end)
        if (req.timeframe,req.start,req.end)!=clock:
            raise ValueError("Portfolio venues need the same timeframe and requested UTC date range")
        # Explicitly require the same base asset and quote convention.
        bases={v["data"]["symbol"].split("/")[0].split(":")[-1]
               for v in items if isinstance(v,dict) and v.get("data",{}).get("symbol")}
        if len(bases)>1:
            raise ValueError("All venues must trade the same base asset for spread comparison")
        vrisk=Risk(**{
            "initial_cash":initial,"product_type":"perp",
            **raw.get("risk",{})
        })
        vrisk.validate()
        if vrisk.product_type not in ("perp","future"):
            raise ValueError("Cross-venue research currently supports linear derivatives only")
        stat=store.data_summary(req)
        if stat["count"]<2 or config.get("refresh"):
            incoming=fetch(req)
            store.upsert_bars(req.cache_key(),incoming)
            stat=store.data_summary(req)
        if stat["count"]<2:
            raise ValueError(f"No historical data for venue {name}")
        inputs.append(store.iter_bars(req))
        books[name]=_Book(name,vrisk)
    signal=_strategy(config.get("strategy",{"type":"spread"}))
    names=list(books)
    cash=initial
    fees=funding_paid=0.0
    desired={name:0.0 for name in names}
    applied=dict(desired)
    fills=[]
    closed=[]
    preview=[]
    stats=_OnlineEquity()
    previous=None
    last_snapshot=None
    n=0

    def trade(name,ts,price,delta,reason):
        nonlocal cash,fees
        book=books[name]
        if abs(delta)<1e-12:
            return
        price=price*(1+math.copysign(book.risk.slippage_bps/10000,delta))
        fee=abs(delta*price)*book.risk.fee_bps/10000
        old=book.position
        if old*delta<0:
            qty=min(abs(old),abs(delta))
            share=qty/abs(old)
            gross=math.copysign(qty,old)*(price-book.entry)
            entry_fee=book.entry_fees*share
            financing=book.funding*share
            exit_fee=fee*qty/abs(delta)
            cash+=gross
            closed.append({"venue":name,"ts":ts,"gross_pnl":round(gross,8),
                           "net_pnl":round(gross-entry_fee-exit_fee-financing,8),
                           "r_multiple":None,"reason":reason})
            book.entry_fees-=entry_fee
            book.funding-=financing
        cash-=fee
        fees+=fee
        new=old+delta
        if abs(new)<1e-12:
            book.position=book.entry=book.entry_fees=book.funding=0.0
        elif old==0 or old*new<0:
            book.position=new
            book.entry=price
            book.entry_fees=fee
            book.funding=0.0
        elif abs(new)>abs(old) and old*delta>0:
            book.entry=(abs(old)*book.entry+abs(delta)*price)/abs(new)
            book.entry_fees+=fee
            book.position=new
        else:
            book.position=new
        fills.append({"venue":name,"ts":ts,"price":round(price,8),
                      "qty":round(delta,8),"fee":round(fee,8),"reason":reason})

    for candles in zip_longest(*inputs):
        if any(bar is None for bar in candles):
            raise ValueError("Venues have unequal history lengths: missing time alignment")
        times={bar.ts for bar in candles}
        if len(times)!=1:
            raise ValueError("Venues have missing or misaligned bars; no forward fill")
        ts=candles[0].ts
        if previous is not None and ts<=previous:
            raise ValueError("Historical timestamps must increase")
        previous=ts
        bars=dict(zip(names,candles))
        # Prior CLOSE signal -> this OPEN fills. Global wallet is shared.
        if desired!=applied:
            current_equity=cash+sum(
                book.position*(bars[name].open-book.entry)
                for name,book in books.items()
            )
            total=sum(abs(x) for x in desired.values())
            for name,book in books.items():
                signal_value=desired[name]
                goal=(current_equity*gross_fraction*signal_value/total/
                      bars[name].open) if total and current_equity>0 else 0.0
                if book.position*goal<0:
                    trade(name,ts,bars[name].open,-book.position,"venue_signal_close")
                trade(name,ts,bars[name].open,goal-book.position,"venue_signal")
            applied=dict(desired)
        for name,book in books.items():
            if book.position and book.risk.product_type=="perp":
                payment=book.position*bars[name].close*bars[name].funding_rate
                cash-=payment
                funding_paid+=payment
                book.funding+=payment
        equity=cash+sum(
            book.position*(bars[name].close-book.entry)
            for name,book in books.items()
        )
        row={"ts":ts,"equity":round(equity,8),
             "position":sum(abs(book.position) for book in books.values())}
        stats.add(row)
        _preview_append(preview,row)
        context={"ts":ts, "cash":cash,"equity":equity,
                 "targets":dict(applied),
                 "positions":{name:book.position for name,book in books.items()},
                 "markets":{name:{"close":b.close,"open":b.open,"high":b.high,
                                  "low":b.low,"volume":b.volume,"funding_rate":b.funding_rate}
                            for name,b in bars.items()}}
        selected=signal(context)
        if not isinstance(selected,dict) or set(selected)!=set(names):
            raise ValueError("Cross-venue strategy must return {venue_id: target} for all venues")
        for name,target in selected.items():
            if isinstance(target,bool) or not isinstance(target,(float,int)) or not math.isfinite(target) or not -1<=target<=1:
                raise ValueError("Cross-venue target must be finite within [-1,1]")
        desired={k:float(v) for k,v in selected.items()}
        n+=1
        last_snapshot=bars
    if n<2:
        raise ValueError("At least two aligned venue candles required")
    for name,book in books.items():
        if book.position:
            trade(name,last_snapshot[name].ts+INTERVALS[clock[0]],
                  last_snapshot[name].close,-book.position,"end_of_test")
    preview[-1]["equity"]=round(cash,8)
    risk=Risk(initial_cash=initial, product_type="perp",market="crypto")
    metrics=_metrics([stats.first,{"ts":stats.last["ts"],"equity":cash,
                                  "position":0}],closed,fees,funding_paid,risk,clock[0])
    metrics=stats.override(metrics,risk,clock[0])
    return {"shared_cash":True,"synchronized_venues":names,"bars":n,
            "metrics":metrics,"equity_preview":preview,"fills":fills,
            "closed_trades":closed,"assumptions":[
              "All venues are treated as fungible linear derivatives, with a single simulated wallet.",
              "Orders execute on next aligned candle OPEN with venue-specific fees and slippage.",
              "Capital cannot actually be transferred instantly across exchanges; independent venue margin/liquidation and DEX gas are NOT modeled.",
              "Strict timestamp alignment: missing candles raise errors and are not filled.",
              "Only spread or opted-in trusted Python cross-venue strategies; Pine multi-venue remains unsupported."
            ]}
