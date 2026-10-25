"""Reproducible local throughput measurement; NOT a forecast of production performance.

Run: python benchmarks/measure.py --bars 120000 --strategy sma
     python benchmarks/measure.py --bars 12000 --strategy pine
"""
from __future__ import annotations

import argparse
import json
import math
import resource
import time

from unibacktest.engine import run_backtest
from unibacktest.model import Bar, Risk
from unibacktest.strategies import create_strategy

PINE = """//@version=6
strategy("SMA benchmark")
fast = ta.sma(close, 10)
slow = ta.sma(close, 30)
if ta.crossover(fast, slow)
    strategy.entry("L", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("L")
"""


def bench(n: int, name: str):
    if n < 2:
        raise ValueError('bars must be >= 2')
    now = 1704067200000
    candles = []
    for i in range(n):
        price = 100 + 0.00002*i + 7*math.sin(i/70)
        candles.append(Bar(now+i*60000, price, price*1.001,
                           price*0.999, price, 100))
    config = ({'type': 'builtin', 'name':'sma_cross', 'options':{'fast':10,'slow':30}}
              if name=='sma' else {'type':'pine','code':PINE})
    strategy = create_strategy(config)
    start = time.perf_counter()
    output=run_backtest(candles,strategy,Risk(product_type='spot',fee_bps=0,slippage_bps=0),timeframe='1m')
    seconds=time.perf_counter()-start
    return {'bars':n,'strategy':name,'time_seconds':round(seconds,6),
            'bars_per_second':round(n/seconds),
            'peak_rss_kb_linux':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'equity_points':len(output['equity']),
            'closed_trades':output['metrics']['closed_trades'],
            'note':'Single process; process RSS includes input and full output history; standalone CPU throughput only'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--bars',type=int,default=120000)
    parser.add_argument('--strategy',choices=['sma','pine'],default='sma')
    args=parser.parse_args()
    print(json.dumps(bench(args.bars,args.strategy),indent=2))