"""Exchange quote contract: freshness, provenance and private API boundary."""
import os
import sys
import types
from fastapi.testclient import TestClient
from unibacktest.api import app
from unibacktest import ticker


def test_authenticated_exchange_last_trade_quote(monkeypatch):
    created=[]
    class FakeExchange:
        has={'fetchTicker':True}
        markets={'ETH/USDT:USDT':{}}
        def __init__(self,opts):
            created.append(opts)
        def load_markets(self):pass
        def fetch_ticker(self,symbol):
            assert symbol=='ETH/USDT:USDT'
            return {'last':2512.25,'timestamp':1793100000000}
    fake=types.ModuleType('ccxt')
    fake.exchanges=['binanceusdm']
    fake.binanceusdm=FakeExchange
    monkeypatch.setitem(sys.modules,'ccxt',fake)
    ticker._exchange_clients.clear()
    ticker._quote_cache.clear()
    query='/api/market/quote?provider=ccxt&exchange=binanceusdm&symbol=ETH%2FUSDT%3AUSDT&market_type=swap'
    client=TestClient(app)
    monkeypatch.delenv('UBT_PUBLIC_DEMO',raising=False)
    assert client.get(query).status_code==401
    secure=TestClient(app,headers={'Authorization':'Bearer '+os.environ['UBT_API_TOKEN']})
    first=secure.get(query)
    assert first.status_code==200,first.text
    payload=first.json()
    assert payload['price']==2512.25
    assert payload['price_type']=='last trade'
    assert payload['market_ts']==1793100000000
    assert payload['cached'] is False
    assert secure.get(query).json()['cached'] is True
    assert len(created)==1
    monkeypatch.setenv('UBT_PUBLIC_DEMO','1')
    assert client.get(query).status_code==403
    ticker._exchange_clients.clear()
    ticker._quote_cache.clear()


def test_quote_never_calls_demo_provider():
    from pytest import raises
    with raises(ValueError,match='Live quotes support'):
        ticker.current_quote('demo','','BTC','swap')


def test_hyperliquid_midpoint_is_not_labeled_last_trade(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):pass
        def json(self):return {'BTC':'70400.25'}
    class FakeClient:
        def __init__(self,timeout):pass
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def post(self,url,json):
            assert json=={'type':'allMids'}
            return FakeResponse()
    monkeypatch.setattr(ticker.httpx,'Client',FakeClient)
    ticker._quote_cache.clear()
    got=ticker.current_quote('hyperliquid','','BTC')
    assert got['price']==70400.25
    assert got['price_type']=='mid (not last trade)'
    ticker._quote_cache.clear()
