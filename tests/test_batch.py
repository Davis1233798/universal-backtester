import pytest
from unibacktest.batch import run_multi_market,decimate_extrema


def test_extrema_preserves_peaks_and_order():
    points=[{'ts':i,'equity':float(i%2*100 + i/100)} for i in range(10000)]
    output=decimate_extrema(points,1200)
    assert len(output)<=1200
    assert output[0]==points[0]
    assert output[-1]==points[-1]
    assert all(x['ts']<y['ts'] for x,y in zip(output,output[1:]))
    assert max(p['equity'] for p in output)==max(p['equity'] for p in points)
    assert min(p['equity'] for p in output)==min(p['equity'] for p in points)


def test_multi_market_demo_two_symbols(monkeypatch, tmp_path):
    # Each worker gets an independent SQLite path, safe to share for synthetic data.
    monkeypatch.setenv('UBT_DB',str(tmp_path/'batch.sqlite3'))
    payload={'strategy':{'type':'builtin','name':'buy_hold'},
     'risk':{'product_type':'spot','fee_bps':0,'slippage_bps':0},'workers':2,
     'markets':[
       {'provider':'demo','symbol':'SYNTH1','start':'2024-01-01','end':'2024-05-01'},
       {'provider':'demo','symbol':'SYNTH2','start':'2024-01-01','end':'2024-05-01'}]}
    out=run_multi_market(payload)
    assert out['count']==2 and out['successful']==2, out['results']
    assert out['results'][0]['data']['symbol']=='SYNTH1'
    assert out['results'][1]['data']['symbol']=='SYNTH2'
    assert out['results'][0]['result']['metrics']['initial_equity']==10000
    assert out['results'][1]['result']['metrics']['initial_equity']==10000
    assert out['results'][0]['result']['metrics']['final_equity'] != out['results'][1]['result']['metrics']['final_equity']
    assert all(len(x['result']['equity_preview']) <= 1200 for x in out['results'])


def test_multi_market_duplicate_is_rejected():
    with pytest.raises(ValueError,match='duplicate'):
        run_multi_market({'markets':[{'provider':'demo','symbol':'BTC'}, {'provider':'demo','symbol':'BTC'}]})


def test_multi_market_errors_isolated(monkeypatch,tmp_path):
    monkeypatch.setenv('UBT_DB',str(tmp_path/'batch.sqlite3'))
    result=run_multi_market({'workers':2,'markets':[
      {'provider':'demo','symbol':'OK','start':'2024-01-01','end':'2024-02-01'},
      {'provider':'demo','symbol':'BAD','start':'2024-03-01','end':'2024-02-01'}]})
    assert result['successful']==1, result['results']
    assert result['failed']==1
    assert result['results'][1]['status']=='error'


def test_batch_api_private_and_public_guard(monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from unibacktest.api import app
    import unibacktest.storage as storage
    monkeypatch.setenv('UBT_DB', str(tmp_path/'api.sqlite3'))
    monkeypatch.setattr(storage, 'DEFAULT_DB', str(tmp_path/'api.sqlite3'))
    monkeypatch.delenv('UBT_PUBLIC_DEMO',raising=False)
    client=TestClient(app)
    cfg={'markets':[{'provider':'demo','symbol':'API1','start':'2024-01-01','end':'2024-02-01'},
                    {'provider':'demo','symbol':'API2','start':'2024-01-01','end':'2024-02-01'}],
         'workers':2,'risk':{'product_type':'spot','fee_bps':0}}
    out=client.post('/api/backtests/batch',json=cfg)
    assert out.status_code==200,out.text
    assert out.json()['successful']==2, out.json()['results']
    view=client.get('/api/candles',params={'provider':'demo','symbol':'API1','start':'2024-01-01','end':'2024-02-01'})
    assert view.status_code==200,view.text
    assert view.json()['represented_bars']>20
    monkeypatch.setenv('UBT_PUBLIC_DEMO','1')
    assert client.post('/api/backtests/batch',json=cfg).status_code==403
    assert client.get('/api/candles',params={'provider':'demo','symbol':'API1','start':'2024-01-01','end':'2024-02-01'}).status_code==403