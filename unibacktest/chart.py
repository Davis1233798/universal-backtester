"""Streaming, viewport-scaled OHLCV query for charts.

Never use aggregated/display candles as backtest input. Backtesting always reads
original candle resolution.  This module exists ONLY for rendering.
"""
from __future__ import annotations

import math
from .model import DataRequest, INTERVALS, iso_ms
from .storage import Store


def read_candles(req: DataRequest, store: Store, max_points: int = 1200) -> dict:
    req.validate()
    if not 10 <= max_points <= 5000:
        raise ValueError('max_points must be in 10..5000 (display only)')
    start, end = iso_ms(req.start), iso_ms(req.end)
    if end <= start:
        raise ValueError('invalid time range')
    step = INTERVALS[req.timeframe]
    bucket_width = max(step, int(math.ceil((end - start)/max_points/step))*step)
    output, working = [], None
    count = 0
    # Query source_key + range using candles primary index; sqlite3 cursor
    # streams rows rather than allocating the whole dataset in RAM.
    with store.connect() as conn:
        cursor = conn.execute('''SELECT ts,open,high,low,close,volume,funding_rate
                 FROM candles WHERE source_key=? AND ts>=? AND ts<? ORDER BY ts''',
                 (req.cache_key(), start, end))
        while True:
            rows = cursor.fetchmany(8192)
            if not rows: break
            for ts, op, hi, lo, cl, vol, funding in rows:
                count += 1
                key = (ts-start)//bucket_width
                if working is None or working['_key'] != key:
                    if working is not None:
                        del working['_key']
                        output.append(working)
                    working={'_key':key,'ts':ts,'last_ts':ts,'open':op,'high':hi,
                             'low':lo,'close':cl,'volume':vol,'funding_rate':funding,
                             'n_bars':1}
                else:
                    working['high']=max(working['high'],hi)
                    working['low']=min(working['low'],lo)
                    working['close']=cl
                    working['volume']+=vol
                    working['funding_rate']+=funding
                    working['last_ts']=ts
                    working['n_bars']+=1
    if working is not None:
        del working['_key']
        output.append(working)
    return {'candles':output,'represented_bars':count,
            'display_points':len(output),'bucket_ms':bucket_width,
            'aggregated_for_display_only':bucket_width>step,
            'warning':'Aggregated display candles must never be fed back to the strategy engine'}


def preview_candles(bars, max_points=900) -> list[dict]:
    """Produce display-only aggregates for in-memory synthetic demonstrations.

    The original full-resolution bars are used for all backtest calculations.
    """
    if max_points < 10:
        raise ValueError('max_points must be >= 10')
    if not bars:
        return []
    stride = math.ceil(len(bars)/max_points)
    output=[]
    for start in range(0,len(bars),stride):
        group=bars[start:start+stride]
        output.append({'ts':group[0].ts,'last_ts':group[-1].ts,
                       'open':group[0].open,'high':max(x.high for x in group),
                       'low':min(x.low for x in group),'close':group[-1].close,
                       'volume':sum(x.volume for x in group),'n_bars':len(group)})
    return output