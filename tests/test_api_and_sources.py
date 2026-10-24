from pathlib import Path
from fastapi.testclient import TestClient
import sys
import types
import pytest
from unibacktest.api import app
from unibacktest.adapters import fetch, _apply_funding
from unibacktest.model import Bar, DataRequest
from unibacktest.storage import Store


def test_public_api_with_synthetic(tmp_path, monkeypatch):
    monkeypatch.setenv('UBT_DB',str(tmp_path/'app.db'))
    import unibacktest.storage as storage
    monkeypatch.setattr(storage,'DEFAULT_DB',str(tmp_path/'app.db'))
    client=TestClient(app)
    assert client.get('/').status_code==200
    assert 'text/html' in client.get('/').headers['content-type']
    assert client.get('/api/health').json()['ok'] is True
    body={'data':{'provider':'demo','start':'2024-01-01','end':'2024-05-01','symbol':'DEMO'},
          'risk':{'product_type':'spot'},'strategy':{'type':'builtin','name':'buy_hold'}}
    r=client.post('/api/backtests',json=body)
    assert r.status_code==200, r.text
    run_id=r.json()['run_id']
    assert client.get('/api/backtests/'+run_id).json()['result']['metrics']['initial_equity']==10000
    assert client.get('/api/backtests').json()


def test_ccxt_adapter_with_mock(monkeypatch):
    fake = types.ModuleType('ccxt')
    fake.exchanges=['mockex']
    class X:
        def __init__(self, opts):
            self.has={'fetchOHLCV':True,'fetchFundingRateHistory':True}
            self.markets={'BTC/USDT:USDT':{}}
            self.timeframes={'1d':'1d'}
        def load_markets(self):pass
        def fetch_ohlcv(self,symbol,timeframe,since=None,limit=1000):
            data=[[1704067200000,100,101,99,100,10], [1704153600000,100,102,99,101,10],
                  [1704240000000,101,103,99,102,10]]
            return [r for r in data if r[0]>=since]
        def fetch_funding_rate_history(self,symbol,since=None,limit=1000):
            return [{'timestamp':1704153600000,'fundingRate':.001}] if since<=1704153600000 else []
    fake.mockex=X
    monkeypatch.setitem(sys.modules,'ccxt',fake)
    req=DataRequest(provider='ccxt',exchange='mockex',symbol='BTC/USDT:USDT',
                    include_funding=True,start='2024-01-01',end='2024-01-04')
    out=fetch(req)
    assert len(out)==3
    assert out[0].funding_rate==pytest.approx(.001)
    assert out[-1].close==102


def test_hyperliquid_adapter_with_mock(monkeypatch):
    class Resp:
        def raise_for_status(self):pass
        def json(self):
            return [{'t':1704067200000,'o':'100','h':'101','l':'99','c':'100','v':'1'},
                    {'t':1704153600000,'o':'100','h':'105','l':'99','c':'102','v':'3'}]
    class C:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,endpoint,json):
            assert json['req']['coin']=='BTC'
            return Resp()
    import unibacktest.adapters as a
    monkeypatch.setattr(a.httpx,'Client',C)
    req=DataRequest(provider='hyperliquid',symbol='BTC',start='2024-01-01',end='2024-01-03')
    out=fetch(req)
    assert len(out)==2 and out[-1].close==102


def test_custom_provider_extension(monkeypatch,tmp_path):
    module=types.ModuleType('fake_vendor')
    module.fetch=lambda req:[Bar(1704067200000,100,100,100,100,1)]
    monkeypatch.setitem(sys.modules,'fake_vendor',module)
    req=DataRequest(provider='plugin:fake_vendor',start='2024-01-01',end='2024-01-02')
    with pytest.raises(PermissionError):fetch(req)
    monkeypatch.setenv('UBT_ALLOW_EXEC','1')
    assert len(fetch(req))==1


def test_yfinance_daily_stock_session_day(monkeypatch):
    pd=pytest.importorskip('pandas')
    class FakeTicker:
        def __init__(self, symbol):self.symbol=symbol
        def history(self, **kwargs):
            i=pd.DatetimeIndex(['2024-01-02 00:00:00+08:00','2024-01-03 00:00:00+08:00'])
            return pd.DataFrame({'Open':[100,101],'High':[102,103],
                                 'Low':[99,100],'Close':[101,102],
                                 'Volume':[123,456]},index=i)
    m=types.ModuleType('yfinance');m.Ticker=FakeTicker
    monkeypatch.setitem(sys.modules,'yfinance',m)
    r=DataRequest(provider='yfinance',symbol='2330.TW',start='2024-01-02',end='2024-01-04')
    bars=fetch(r)
    assert len(bars)==2
    assert bars[0].ts==1704153600000  # local 2024-01-02 -> UTC date 2024-01-02
