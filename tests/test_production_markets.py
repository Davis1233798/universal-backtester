"""Production market loading must use real cached/remote bars, never synthetic demo prices."""
from pathlib import Path
import os

from fastapi.testclient import TestClient

from unibacktest.api import app
from unibacktest.model import Bar, iso_ms


def _request(symbol="ETH/USDT:USDT"):
    return {
        "data": {
            "provider":"ccxt", "exchange":"binanceusdm", "market_type":"swap",
            "symbol":symbol, "timeframe":"1h",
            "start":"2024-01-01","end":"2024-01-02",
            "include_funding":False
        },
        "max_points":1500
    }


def test_real_market_chart_populates_cache_and_accepts_eth_sol(monkeypatch,tmp_path):
    monkeypatch.delenv("UBT_PUBLIC_DEMO",raising=False)
    monkeypatch.setenv("UBT_DB",str(tmp_path/"production-candles.sqlite3"))
    import unibacktest.storage as storage
    monkeypatch.setattr(storage,"DEFAULT_DB",str(tmp_path/"production-candles.sqlite3"))
    requests=[]
    def fake_fetch(req):
        requests.append(req.symbol)
        ts=iso_ms(req.start)
        out=[]
        for i in range(24):
            op=100+i
            out.append(Bar(ts+i*3600000,op,op+2,op-1,op+1,100.0))
        return out
    monkeypatch.setattr("unibacktest.service.fetch",fake_fetch)
    client=TestClient(app,headers={"Authorization":"Bearer "+os.environ["UBT_API_TOKEN"]})
    for symbol in ("ETH/USDT:USDT","SOL/USDT:USDT"):
        payload=_request(symbol)
        reply=client.post("/api/candles/load",json=payload)
        assert reply.status_code==200,reply.text
        data=reply.json()
        assert data["provider"]=="ccxt"
        assert data["symbol"]==symbol
        assert data["represented_bars"]==24
        assert data["display_points"]==24
        assert data["candles"][0]["open"]==100
        assert data["candles"][-1]["close"]==124
        assert client.post("/api/candles/load",json=payload).status_code==200
    assert requests==["ETH/USDT:USDT","SOL/USDT:USDT"]
    refreshed=client.post("/api/candles/load",json={**_request(),"refresh":True})
    assert refreshed.status_code==200,refreshed.text
    # Historical refresh no longer re-downloads complete fixed-date data.
    # Only current-market view triggers bounded live-tail synchronization.
    assert requests==["ETH/USDT:USDT","SOL/USDT:USDT"]


def test_chart_loader_rejects_public_and_unauthorized(monkeypatch,tmp_path):
    monkeypatch.setenv("UBT_DB",str(tmp_path/"guard.sqlite3"))
    import unibacktest.storage as storage
    monkeypatch.setattr(storage,"DEFAULT_DB",str(tmp_path/"guard.sqlite3"))
    monkeypatch.delenv("UBT_PUBLIC_DEMO",raising=False)
    client=TestClient(app)
    assert client.post("/api/candles/load",json=_request()).status_code==401
    authorized=TestClient(app,headers={"Authorization":"Bearer "+os.environ["UBT_API_TOKEN"]})
    assert authorized.post("/api/candles/load",json={
        **_request(), "data":{**_request()["data"],"provider":"demo"}
    }).status_code==422
    monkeypatch.setenv("UBT_PUBLIC_DEMO","1")
    assert client.post("/api/candles/load",json=_request()).status_code==403


def test_production_frontend_defaults_to_real_venue_and_has_discovery():
    source=Path("frontend/src/api.ts").read_text(encoding="utf-8")
    app=Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    assert "data:{provider:'ccxt',exchange:'binanceusdm'" in source
    assert "client.post<" in app and "'/api/candles/load'" in app
    assert "搜尋交易所所有上市商品" in app
    assert "['BTC','ETH','SOL','XRP','DOGE'" in app
    assert "exchange:'bybit'" in app
    assert "exchange:'okx'" in app
    assert "provider:'hyperliquid'" in app
    assert "provider:'yfinance'" in app


def test_extending_range_backwards_fetches_older_market_history(monkeypatch,tmp_path):
    monkeypatch.delenv("UBT_PUBLIC_DEMO",raising=False)
    monkeypatch.setenv("UBT_DB",str(tmp_path/"range-extension.sqlite3"))
    import unibacktest.storage as storage
    monkeypatch.setattr(storage,"DEFAULT_DB",str(tmp_path/"range-extension.sqlite3"))
    called=[]
    def fake_fetch(req):
        called.append(req.start)
        ts=iso_ms(req.start)
        return [Bar(ts+i*3600000,100,101,99,100.5,5) for i in range(24)]
    monkeypatch.setattr("unibacktest.service.fetch",fake_fetch)
    client=TestClient(app,headers={"Authorization":"Bearer "+os.environ["UBT_API_TOKEN"]})
    one=_request("ETH/USDT:USDT")
    one["data"]["start"]="2024-01-02"
    one["data"]["end"]="2024-01-03"
    first=client.post("/api/candles/load",json=one)
    assert first.status_code==200,first.text
    assert first.json()["represented_bars"]==24
    two=_request("ETH/USDT:USDT")
    two["data"]["end"]="2024-01-03"
    second=client.post("/api/candles/load",json=two)
    assert second.status_code==200,second.text
    assert second.json()["represented_bars"]==48
    assert [v[:10] for v in called]==["2024-01-02","2024-01-01"]
