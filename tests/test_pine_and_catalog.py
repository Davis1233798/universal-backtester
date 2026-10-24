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
        PineSubsetStrategy('strategy("X")\nstrategy.exit("L", "L", stop=10)')

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