"""Live OHLCV and exact-resolution chart paging regression tests."""
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from unibacktest.api import app
from unibacktest.chart import read_candles
from unibacktest.live import sync_recent_candles, attach_latest_to_chart
from unibacktest.model import Bar, DataRequest, iso_ms
from unibacktest.storage import Store


def _bars(start, n, step=60000):
    return [Bar(start+i*step, 100+i, 101+i, 99+i, 100.5+i, 50+i)
            for i in range(n)]


def test_live_partial_never_enters_backtest_database(tmp_path):
    store=Store(str(tmp_path/'live.sqlite3'))
    current=iso_ms('2026-10-27T12:02:30Z')
    req=DataRequest(provider='ccxt',exchange='binanceusdm',symbol='ETH/USDT:USDT',
                    timeframe='1m',start='2026-10-27T11:00:00Z',
                    end='2026-10-28T00:00:00Z')
    full=_bars(iso_ms('2026-10-27T11:59:00Z'),4)
    captured=[]
    def fake_exchange(query):
        captured.append(query)
        return full
    snapshot=sync_recent_candles(req,store,now_ms=current,fetcher=fake_exchange)
    assert len(captured)==1
    assert iso_ms(captured[0].start) >= current-5*60000
    assert snapshot['partial']['ts']==iso_ms('2026-10-27T12:02:00Z')
    assert snapshot['partial']['is_partial'] is True
    stored=store.get_bars(req)
    assert len(stored)==3
    assert all(x.ts+60000<=current for x in stored)
    chart=read_candles(req,store,1500)
    output=attach_latest_to_chart(chart,snapshot)
    assert len(output['candles'])==4
    assert output['candles'][-1]['is_partial'] is True
    assert output['partial_candle'] is True
    assert output['is_live'] if 'is_live' in output else True


def test_live_does_not_zero_existing_funding(tmp_path):
    store=Store(str(tmp_path/'funding.sqlite3'))
    now=iso_ms('2026-10-27T12:02:30Z')
    req=DataRequest(provider='ccxt',exchange='binanceusdm',symbol='BTC/USDT:USDT',
                    timeframe='1m',start='2026-10-27T11:00:00Z',
                    end='2026-10-28T00:00:00Z',include_funding=True)
    first=Bar(iso_ms('2026-10-27T12:00:00Z'),100,101,99,100,10,0.0001)
    store.upsert_bars(req.cache_key(),[first])
    snapshot=sync_recent_candles(req,store,now_ms=now,fetcher=lambda _: _bars(first.ts,3))
    assert snapshot['partial'] is not None
    assert store.get_bars(req)[0].funding_rate==0.0001
    assert len(store.get_bars(req))==1


def test_exact_native_chart_window_and_earlier_page(monkeypatch,tmp_path):
    from unibacktest.model import iso_ms
    import unibacktest.storage as storage
    monkeypatch.setattr(storage,'DEFAULT_DB',str(tmp_path/'pages.sqlite3'))
    monkeypatch.setenv('UBT_DB',str(tmp_path/'pages.sqlite3'))
    monkeypatch.delenv('UBT_PUBLIC_DEMO',raising=False)
    first=iso_ms('2024-01-01T00:00:00Z')
    def fake_fetch(req):
        return [b for b in _bars(first,48,3600000) if
                iso_ms(req.start)<=b.ts<iso_ms(req.end)]
    monkeypatch.setattr('unibacktest.service.fetch',fake_fetch)
    client=TestClient(app,headers={'Authorization':'Bearer '+os.environ['UBT_API_TOKEN']})
    payload={'data':{'provider':'ccxt','exchange':'binanceusdm',
                     'symbol':'ETH/USDT:USDT','timeframe':'1h',
                     'start':'2024-01-01','end':'2024-01-03'},
             'max_points':24}
    recent=client.post('/api/candles/load',json=payload)
    assert recent.status_code==200,recent.text
    data=recent.json()
    assert data['exact_timeframe'] is True
    assert len(data['candles'])==24
    assert data['candles'][0]['ts']==first+24*3600000
    assert data['candles'][-1]['ts']==first+47*3600000
    older=client.post('/api/candles/load',json={**payload,'view_end_ms':first+24*3600000})
    assert older.status_code==200,older.text
    back=older.json()
    assert back['exact_timeframe']
    assert back['candles'][0]['ts']==first
    assert back['candles'][-1]['ts']==first+23*3600000
    assert back['is_live'] is False
