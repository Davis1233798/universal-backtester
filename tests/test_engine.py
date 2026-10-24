from datetime import datetime, timezone
import pytest
from unibacktest.engine import run_backtest
from unibacktest.model import Bar, Risk
from unibacktest.strategies import BuiltinStrategy

D = 86400000


def bars(prices):
    return [Bar(i*D, p, p*1.01, p*.99, p, 500) for i, p in enumerate(prices)]


def test_next_open_no_lookahead():
    candles = [Bar(0,100,100,100,100,1), Bar(D,150,150,150,150,1),
               Bar(2*D,160,160,160,160,1)]
    class OnlyFirst:
        def __call__(self, ctx):return 1.0
    res = run_backtest(candles, OnlyFirst(), Risk(product_type="spot",fee_bps=0,slippage_bps=0))
    assert res['fills'][0]['ts'] == D
    assert res['fills'][0]['price'] == 150
    assert res['metrics']['final_equity'] == pytest.approx(10666.666667, abs=.00001)


def test_funding_paid_long_received_short():
    candles = [Bar(0,100,100,100,100,1),Bar(D,100,100,100,100,1,.01),Bar(2*D,100,100,100,100,1)]
    long = run_backtest(candles, lambda _: 1, Risk(product_type="perp",fee_bps=0,slippage_bps=0))
    short = run_backtest(candles, lambda _: -1, Risk(product_type="perp",fee_bps=0,slippage_bps=0))
    assert long['metrics']['final_equity']==9900
    assert short['metrics']['final_equity']==10100


def test_liquidation_triggered_by_extreme():
    candles = [Bar(0,100,100,100,100,1), Bar(D,100,110,20,100,1), Bar(2*D,100,100,100,100,1)]
    res = run_backtest(candles,lambda _:1,Risk(product_type="perp",leverage=3,fee_bps=0,slippage_bps=0))
    assert res['liquidations']==1
    assert res['metrics']['final_equity'] < 0
    assert res['fills'][1]['reason']=='liquidation_extreme'


def test_spot_rejects_short():
    with pytest.raises(ValueError, match='cannot be negative'):
        run_backtest(bars([100,101,102]), lambda _: -1,Risk(product_type="spot"))


def test_risk_limits_and_bad_signals():
    with pytest.raises(ValueError):Risk(leverage=200).validate()
    with pytest.raises(ValueError,match='target'):
        run_backtest(bars([100,101,102]),lambda _:float('nan'),Risk())


def test_long_hold_no_same_close_rebalance():
    res = run_backtest(bars([100,100,110,120,130]), lambda _: 1, Risk(product_type='spot',fee_bps=0,slippage_bps=0))
    assert len(res['fills'])==2
    assert res['metrics']['final_equity']==13000


def test_invalid_candle():
    with pytest.raises(ValueError):Bar(0,100,90,95,100,100)


def test_builtin_sma_signal():
    st=BuiltinStrategy('sma_cross',{'fast':2,'slow':3})
    assert st({'bars':[b.to_dict() for b in bars([1,2,3])],'target':0})==1
