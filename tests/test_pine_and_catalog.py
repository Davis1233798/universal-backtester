import os
import pytest
from unibacktest.pine import PineSubsetStrategy
from unibacktest.service import execute
from unibacktest.storage import Store

PINE = """//@version=6
strategy("MA Cross", overlay=true)
fast = input.int(2, "Fast")
slow = input.int(4, "Slow")
f = ta.sma(close, fast)
s = ta.sma(close, slow)
if ta.crossover(f, s)
    strategy.entry("L", strategy.long)
if ta.crossunder(f, s)
    strategy.close("L")
"""

def test_pine_subset_cross_and_close():
    strat = PineSubsetStrategy(PINE)
    prices = [1,1,1,1,2,3,4,5,3,2,1]
    targets=[]
    for i in range(len(prices)):
        bars=[dict(ts=j*86400000,open=p,high=p+1,low=p-.1,close=p,volume=10) for j,p in enumerate(prices[:i+1])]
        targets.append(strat({'bars':bars, 'target':targets[-1] if targets else 0, 'position':0}))
    assert targets[3]==0
    assert targets[4]==1
    assert targets[8]==1
    assert targets[9]==0

def test_pine_subset_rejects_unsafe_code():
    bad = ['import os', 'x = __import__("os")', 'x = open("/etc/passwd")',
           'while true:\n    x = close', 'x = close.__class__', 'x = ta.unknown(close,2)']
    for block in bad:
        with pytest.raises(ValueError):
            PineSubsetStrategy('strategy("Unsafe")\n'+block+'\nstrategy.entry("L", strategy.long)')

def test_pine_subset_rejects_unknown_trade_functions():
    with pytest.raises(ValueError,match='Unsupported Pine statement'):
        PineSubsetStrategy('strategy("X")\nstrategy.cancel("L")')

def test_pine_backtest_on_demo_data(tmp_path):
    cfg={'data':{'provider':'demo','symbol':'DEMO','start':'2024-01-01','end':'2024-07-01'},
         'risk':{'product_type':'spot'},'strategy':{'type':'pine','code':PINE}}
    output=execute(cfg,Store(str(tmp_path/'pine.sqlite3')))
    assert output['bars']>120
    assert output['metrics']['final_equity']>0

def test_dynamic_ccxt_market_catalog(monkeypatch):
    import sys, types
    fake=types.ModuleType('ccxt')
    fake.exchanges=['mockex']
    class Exchange:
        def __init__(self,*args,**kwargs): pass
        def load_markets(self):
            return {
                'BTC/USDT:USDT':{'symbol':'BTC/USDT:USDT','type':'swap','swap':True,'base':'BTC','quote':'USDT','settle':'USDT','active':True},
                'FOO/USDT:USDT':{'symbol':'FOO/USDT:USDT','type':'swap','swap':True,'base':'FOO','quote':'USDT','settle':'USDT','active':True},
                'BTC/USDT':{'symbol':'BTC/USDT','type':'spot','spot':True,'base':'BTC','quote':'USDT','active':True},
                'OLD/USDT:USDT':{'symbol':'OLD/USDT:USDT','type':'swap','swap':True,'base':'OLD','quote':'USDT','active':False}}
        def close(self):pass
    fake.mockex=Exchange
    monkeypatch.setitem(sys.modules,'ccxt',fake)
    from unibacktest.catalog import search_markets, _ccxt_markets
    _ccxt_markets.cache_clear()
    result=search_markets('ccxt','foo','mockex','swap')
    assert [x['symbol'] for x in result['items']]==['FOO/USDT:USDT']
    assert search_markets('ccxt','btc','mockex','spot')['items'][0]['symbol']=='BTC/USDT'
    with pytest.raises(ValueError):search_markets('ccxt','BTC','unknown','swap')


def test_dynamic_stock_search(monkeypatch):
    import sys, types
    fake=types.ModuleType('yfinance')
    class Search:
        def __init__(self,*args,**kwargs):
            self.quotes=[{'symbol':'2330.TW','shortname':'TSMC','exchange':'TAI','quoteType':'EQUITY'}]
    fake.Search=Search
    monkeypatch.setitem(sys.modules,'yfinance',fake)
    from unibacktest.catalog import search_markets
    result=search_markets('yfinance','TSMC')
    assert result['items'][0]['symbol']=='2330.TW'

def test_hyperliquid_native_market_catalog(monkeypatch):
    import unibacktest.catalog as c
    monkeypatch.setattr(c, '_hyperliquid_universe', lambda bucket:[
        {'symbol':'BTC','type':'swap','exchange':'hyperliquid'},
        {'symbol':'ETH','type':'swap','exchange':'hyperliquid'}])
    result=c.search_markets('hyperliquid','eth')
    assert result['items'][0]['symbol']=='ETH'
    assert result['matched_count']==1

def test_public_pine_api_works_without_exec(monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from unibacktest.api import app
    monkeypatch.setenv('UBT_PUBLIC_DEMO','1')
    monkeypatch.delenv('UBT_ALLOW_EXEC', raising=False)
    monkeypatch.setenv('UBT_DB',str(tmp_path/'unused.db'))
    client = TestClient(app, headers={"Authorization":"Bearer "+os.environ["UBT_API_TOKEN"]})
    body={'data':{'provider':'demo','symbol':'DEMO','start':'2024-01-01','end':'2024-06-01'},
          'risk':{'product_type':'spot','leverage':1},
          'strategy':{'type':'pine','code':PINE}}
    response=client.post('/api/backtests',json=body)
    assert response.status_code==200, response.text
    assert response.json()['run_id']=='demo-not-saved'
    assert not (tmp_path/'unused.db').exists()
    body['strategy']['code']='strategy("X")\nimport os\nstrategy.entry("L",strategy.long)'
    assert client.post('/api/backtests',json=body).status_code==422
    assert client.get('/api/markets?provider=ccxt&q=BTC&exchange=binance').status_code==403

def test_pine_lookback_beyond_five_hundred():
    from unibacktest.engine import run_backtest
    from unibacktest.model import Bar, Risk
    day=86400000
    bars=[Bar(i*day,100.,100.,100.,100.,1.) for i in range(1205)]
    script='''//@version=6
strategy("Deep history")
long_average = ta.sma(close, 1001)
if not na(long_average) and close[1000] > 0
    strategy.entry("L", strategy.long)
'''
    res=run_backtest(bars,PineSubsetStrategy(script),
                     Risk(product_type="spot",fee_bps=0,slippage_bps=0))
    assert res['bars']==1205
    assert res['fills'][0]['ts']==1001*day


def test_pine_long_variable_history():
    from unibacktest.engine import run_backtest
    from unibacktest.model import Bar, Risk
    day=86400000
    candles=[Bar(i*day,100+i*.01,100+i*.01,100+i*.01,100+i*.01,1.) for i in range(1006)]
    script='''//@version=6
strategy("Variable history")
v = close
if not na(v[1000]) and v > v[1000]
    strategy.entry("L", strategy.long)
'''
    out=run_backtest(candles,PineSubsetStrategy(script),Risk(product_type="spot",fee_bps=0,slippage_bps=0))
    assert out['fills'][0]['ts']==1001*day


def test_pine_strategy_exit_stop_and_limit_supported():
    from unibacktest.engine import run_backtest
    from unibacktest.model import Bar, Risk
    day=86400000
    candles=[Bar(0,100,100,100,100,1),
             Bar(day,100,100,100,100,1),
             Bar(2*day,100,108,94,100,1),
             Bar(3*day,100,100,100,100,1)]
    code='''//@version=6
strategy("Bracket")
strategy.entry("L", strategy.long)
strategy.exit("XL","L",stop=95,limit=105)
'''
    result=run_backtest(candles,PineSubsetStrategy(code),
                        Risk(product_type="spot",fee_bps=0,slippage_bps=0))
    assert result['closed_trades'][0]['reason']=='stop_market'
    assert result['closed_trades'][0]['exit_price']==95


def test_pine_strategy_exit_rejects_trailing_and_qty():
    for fragment in ("trail_points=10","qty_percent=50","stop=0"):
        src='strategy("X")\nstrategy.entry("L",strategy.long)\nstrategy.exit("XL","L",'+fragment+')'
        if fragment=="stop=0":
            strat=PineSubsetStrategy(src)
            with pytest.raises(ValueError,match='positive finite'):
                strat({'bars':[{'open':100,'high':100,'low':100,'close':100,'volume':1,'ts':0}],
                      'target':0,'position':0})
        else:
            strat=PineSubsetStrategy(src)
            with pytest.raises(ValueError,match='Unsupported strategy.exit'):
                strat({'bars':[{'open':100,'high':100,'low':100,'close':100,'volume':1,'ts':0}],
                       'target':0,'position':0})


def test_streaming_pine_deep_history_matches_regular():
    from unibacktest.model import Bar,Risk
    from unibacktest.engine import run_backtest
    day=86400000
    candles=[Bar(i*day,100+i*.01,100+i*.01,100+i*.01,100+i*.01,1.)
             for i in range(1205)]
    code='''//@version=6
strategy("long period")
period = input.int(1001, "period")
ma = ta.sma(close, period)
if not na(ma) and close[1000] > 0
    strategy.entry("L",strategy.long)
'''
    a=run_backtest(candles,PineSubsetStrategy(code),Risk(product_type="spot",fee_bps=0,slippage_bps=0))
    b=run_backtest(iter(candles),PineSubsetStrategy(code),
                   Risk(product_type="spot",fee_bps=0,slippage_bps=0),streaming=True)
    assert a["fills"][0]["ts"]==b["fills"][0]["ts"]==1001*day
    assert a["metrics"]["final_equity"]==pytest.approx(b["metrics"]["final_equity"])
