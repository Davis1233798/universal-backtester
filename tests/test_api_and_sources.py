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


def test_public_demo_is_stateless_and_rejects_unsafe_operations(tmp_path, monkeypatch):
    monkeypatch.setenv('UBT_PUBLIC_DEMO', '1')
    monkeypatch.setenv('UBT_DB', str(tmp_path/'should_not_exist.db'))
    client = TestClient(app)
    assert client.get('/api/health').json()['public_demo'] is True
    providers = client.get('/api/sources').json()
    assert providers['providers'] == ['demo']
    payload = {
        'data': {'provider': 'demo', 'symbol': 'SYNTHETIC',
                 'start': '2024-01-01', 'end': '2024-06-01'},
        'risk': {'product_type': 'spot', 'leverage': 1},
        'strategy': {'type': 'builtin', 'name': 'sma_cross'}
    }
    good = client.post('/api/backtests', json=payload)
    assert good.status_code == 200, good.text
    assert good.json()['run_id'] == 'demo-not-saved'
    assert good.json()['metrics']['initial_equity'] == 10000
    assert not (tmp_path/'should_not_exist.db').exists()
    payload['data']['provider'] = 'csv'
    payload['data']['csv_path'] = '/etc/passwd'
    assert client.post('/api/backtests',json=payload).status_code == 422
    payload['data']['provider'] = 'demo'
    payload['strategy'] = {'type': 'process', 'command': ['sh', '-c', 'echo hijack']}
    assert client.post('/api/backtests',json=payload).status_code == 422
    payload['strategy'] = {'type': 'builtin','name': 'buy_hold'}
    payload['data']['timeframe'] = '1m'
    assert client.post('/api/backtests',json=payload).status_code == 422
    for route in ('/api/backtests','/api/backtests/random','/api/jobs'):
        assert client.get(route).status_code == 403
    assert client.post('/api/jobs',json=payload).status_code == 403
    assert client.patch('/api/jobs/random?active=true').status_code == 403


def test_pine_editor_visible_by_default_in_web_ui():
    client=TestClient(app)
    html=client.get('/').text
    assert 'id="pine-editor">' in html
    assert '<option value="pine" selected>' in html
    assert 'id="pineCode"' in html
    assert 'id="market-demo-info" hidden' in html
    assert "document.querySelector('.sub').textContent" in html


def test_metrics_r_reference_ui_and_deployment_health(monkeypatch):
    client=TestClient(app)
    html=client.get('/').text
    assert 'id="rRef"' in html
    assert '營利因子 PF' in html
    assert '平均 R' in html
    assert 'id="closedRows"' in html
    monkeypatch.setenv('RENDER_GIT_COMMIT','abcdef012345')
    assert client.get('/api/health').json()['deployed_commit']=='abcdef012345'


def test_private_backtest_sqlite_stream_mode(monkeypatch,tmp_path):
    import unibacktest.storage as storage
    db=str(tmp_path/'stream-test.sqlite3')
    monkeypatch.setattr(storage,'DEFAULT_DB',db)
    monkeypatch.delenv('UBT_PUBLIC_DEMO',raising=False)
    from fastapi.testclient import TestClient
    from unibacktest.api import app
    client=TestClient(app)
    cfg={'data':{'provider':'demo','symbol':'STREAM','start':'2024-01-01','end':'2024-04-01'},
         'risk':{'product_type':'spot','fee_bps':0,'slippage_bps':0},
         'strategy':{'type':'builtin','name':'buy_hold'},'streaming':True}
    response=client.post('/api/backtests',json=cfg)
    assert response.status_code==200,response.text
    assert response.json()['streaming_preview_only']
    assert response.json()['bars']==91
    assert response.json()['coverage']['streaming_from_sqlite']
