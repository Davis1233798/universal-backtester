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


def test_profit_factor_and_average_r_are_net():
    from unibacktest.model import Bar
    prices = [100, 100, 110, 100, 90, 90]
    candles = [Bar(i*D,p,p,p,p,1) for i,p in enumerate(prices)]
    responses=iter([1,0,1,0,0])
    result=run_backtest(candles,lambda _: next(responses),
        Risk(product_type='spot',fee_bps=0,slippage_bps=0,r_reference_stop_pct=10))
    trades=result['closed_trades']
    assert len(trades)==2
    assert trades[0]['net_pnl']==pytest.approx(1000)
    assert trades[1]['net_pnl']==pytest.approx(-1100)
    m=result['metrics']
    assert m['profit_factor']==pytest.approx(1000/1100,abs=1e-6)
    assert m['profit_factor_status']=='calculated'
    assert m['win_rate_pct']==50
    assert trades[0]['r_multiple']==1
    assert trades[1]['r_multiple']==-1
    assert m['average_r']==0
    assert m['net_profit']==pytest.approx(-100)


def test_fees_and_funding_reduce_trade_net_and_r():
    candles=[Bar(0,100,100,100,100,1),Bar(D,100,100,100,100,1,.01),
             Bar(2*D,100,100,100,100,1)]
    res=run_backtest(candles,lambda _:1,
        Risk(product_type='perp',fee_bps=100,slippage_bps=0,r_reference_stop_pct=10))
    t=res['closed_trades'][0]
    assert t['gross_pnl']==0
    assert t['entry_fee']==pytest.approx(100)
    assert t['exit_fee']==pytest.approx(100)
    assert t['funding_paid_net']==pytest.approx(100)
    assert t['net_pnl']==pytest.approx(-300)
    assert t['r_multiple']==pytest.approx(-.3)
    assert res['metrics']['profit_factor']==0
    assert res['metrics']['win_rate_pct']==0
    assert res['metrics']['average_r']==-.3


def test_profit_factor_no_losses_and_r_undefined_without_reference():
    res=run_backtest([Bar(i*D,p,p,p,p,1) for i,p in enumerate([100,100,110])],
        lambda _:1, Risk(product_type='spot',fee_bps=0,slippage_bps=0))
    assert res['metrics']['profit_factor'] is None
    assert res['metrics']['profit_factor_status']=='no_losses'
    assert res['metrics']['average_r'] is None
    assert res['closed_trades'][0]['r_multiple'] is None


def test_r_reporting_reference_validation():
    for pct in (0,101,float('nan')):
        with pytest.raises(ValueError,match='r_reference_stop_pct'):
            Risk(r_reference_stop_pct=pct).validate()


def test_partial_closes_allocate_entry_and_exit_fees():
    candles=[Bar(i*D,100,100,100,100,1) for i in range(5)]
    choices=iter([1,.5,0,0])
    res=run_backtest(candles,lambda _:next(choices),
        Risk(product_type='perp',fee_bps=100,slippage_bps=0,r_reference_stop_pct=5))
    trades=res['closed_trades']
    assert len(trades)==2
    assert sum(t['net_pnl'] for t in trades)==pytest.approx(res['metrics']['net_profit'],abs=.0001)
    assert sum(t['entry_fee'] for t in trades)==pytest.approx(100)
    assert sum(t['exit_fee'] for t in trades)==pytest.approx(res['metrics']['fees_paid']-100)


def test_stop_gap_worse_open_and_limit_fill():
    from unibacktest.pine import PineSubsetStrategy
    code='''//@version=6
strategy("Exit")
strategy.entry("L",strategy.long)
strategy.exit("XL","L",stop=95,limit=115)
'''
    candle=[Bar(0,100,100,100,100,1),Bar(D,100,100,100,100,1),
            Bar(2*D,90,95,88,92,1),Bar(3*D,92,92,92,92,1)]
    outcome=run_backtest(candle,PineSubsetStrategy(code),
                         Risk(product_type="spot",fee_bps=0,slippage_bps=0))
    assert outcome['closed_trades'][0]['exit_price']==90
    assert outcome['closed_trades'][0]['reason']=='stop_market'
    bullish=[Bar(0,100,100,100,100,1),Bar(D,100,100,100,100,1),
             Bar(2*D,120,123,110,120,1),Bar(3*D,120,120,120,120,1)]
    got=run_backtest(bullish,PineSubsetStrategy(code),
                     Risk(product_type="spot",fee_bps=0,slippage_bps=0))
    assert got['closed_trades'][0]['exit_price']==120
    assert got['closed_trades'][0]['reason']=='take_profit_limit'


def test_streaming_engine_matches_full_simple_strategy():
    from unibacktest.engine import run_backtest
    candles=bars([100+(i%23)*.1 for i in range(3000)])
    risk=Risk(product_type="spot",fee_bps=0,slippage_bps=0)
    full=run_backtest(candles,BuiltinStrategy("sma_cross",{"fast":10,"slow":30}),risk)
    stream=run_backtest(iter(candles),BuiltinStrategy("sma_cross",{"fast":10,"slow":30}),risk,streaming=True)
    assert stream["bars"]==len(candles)
    assert stream["streaming_preview_only"]
    assert len(stream["equity"])<=2000
    assert stream["metrics"]["final_equity"]==pytest.approx(full["metrics"]["final_equity"])
    assert stream["metrics"]["max_drawdown_pct"]==pytest.approx(full["metrics"]["max_drawdown_pct"],abs=.001)
