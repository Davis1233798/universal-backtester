import os
from fastapi.testclient import TestClient
from unibacktest.portfolio import run_portfolio
from unibacktest.api import app
import pytest


def sample():
    return {
        "portfolio":{"initial_cash":10000,"gross_notional_fraction":0.8},
        "strategy":{"type":"spread","entry_bps":5,"exit_bps":1},
        "venues":[
            {"id":"cex","data":{"provider":"demo","exchange":"binance","symbol":"BTC","start":"2024-01-01","end":"2024-04-01","timeframe":"1d"},
             "risk":{"product_type":"perp","fee_bps":4}},
            {"id":"dex","data":{"provider":"demo","exchange":"hyperliquid","symbol":"BTC","start":"2024-01-01","end":"2024-04-01","timeframe":"1d"},
             "risk":{"product_type":"perp","fee_bps":5}}
        ]
    }


def test_shared_wallet_cross_venue_spread(tmp_path,monkeypatch):
    monkeypatch.setenv('UBT_DB',str(tmp_path/'shared.sqlite'))
    from unibacktest.storage import Store
    out=run_portfolio(sample(),Store(str(tmp_path/'shared.sqlite')))
    assert out["shared_cash"] is True
    assert out["synchronized_venues"]==["cex","dex"]
    assert out["bars"]==91
    assert out["metrics"]["final_equity"]>0
    assert len(out["equity_preview"])==91
    assert set(f["venue"] for f in out["fills"])=={"cex","dex"}


def test_shared_portfolio_fails_on_unaligned_range(tmp_path):
    from unibacktest.storage import Store
    cfg=sample()
    cfg["venues"][1]["data"]["start"]="2024-01-05"
    with pytest.raises(ValueError,match="same timeframe"):
        run_portfolio(cfg,Store(str(tmp_path/'misaligned.sqlite')))


def test_shared_portfolio_disallows_other_base(tmp_path):
    from unibacktest.storage import Store
    cfg=sample()
    cfg["venues"][1]["data"]["symbol"]="ETH"
    with pytest.raises(ValueError,match="same base asset"):
        run_portfolio(cfg,Store(str(tmp_path/'wrongasset.sqlite')))


def test_cross_venue_custom_python_requires_trusted_host(monkeypatch,tmp_path):
    from unibacktest.storage import Store
    script=tmp_path/'spread.py'
    script.write_text("def on_venues(ctx):\n    return {'cex':1,'dex':-1}\n")
    cfg=sample()
    cfg["strategy"]={"type":"python","path":str(script)}
    monkeypatch.delenv('UBT_ALLOW_EXEC',raising=False)
    with pytest.raises(PermissionError,match='UBT_ALLOW_EXEC'):
        run_portfolio(cfg,Store(str(tmp_path/'auth.sqlite')))
    monkeypatch.setenv('UBT_ALLOW_EXEC','1')
    result=run_portfolio(cfg,Store(str(tmp_path/'auth.sqlite')))
    assert result['metrics']['closed_trades']>=2


def test_cross_venue_private_http_guard(monkeypatch,tmp_path):
    monkeypatch.setenv('UBT_PUBLIC_DEMO','1')
    client=TestClient(app, headers={"Authorization":"Bearer "+os.environ["UBT_API_TOKEN"]})
    assert client.post('/api/portfolio/backtests',json=sample()).status_code==403
    monkeypatch.delenv('UBT_PUBLIC_DEMO',raising=False)
    monkeypatch.setenv('UBT_DB',str(tmp_path/'rest.sqlite'))
    res=client.post('/api/portfolio/backtests',json=sample())
    assert res.status_code==200,res.text
    assert res.json()['shared_cash'] is True
