from unibacktest.chart import read_candles
from unibacktest.model import DataRequest, Bar, INTERVALS
from unibacktest.storage import Store


def test_big_dataset_chart_is_bounded_and_preserves_extremes(tmp_path):
    store=Store(str(tmp_path/'bars.db'))
    req=DataRequest(provider='demo',symbol='SYNTHETIC',timeframe='1m',start='2024-01-01',end='2024-05-01')
    from unibacktest.model import iso_ms
    start=iso_ms(req.start)
    bars=[Bar(start+i*60000,100,120 if i==35000 else 100,
              30 if i==50000 else 100,100,1) for i in range(100000)]
    store.upsert_bars(req.cache_key(),bars)
    out=read_candles(req,store,max_points=500)
    assert out['represented_bars']==100000
    assert out['display_points']<=500
    assert max(x['high'] for x in out['candles'])==120
    assert min(x['low'] for x in out['candles'])==30
    assert out['aggregated_for_display_only'] is True
    assert sum(x['volume'] for x in out['candles'])==100000
    assert sum(x['n_bars'] for x in out['candles'])==100000


def test_short_range_uses_actual_bars(tmp_path):
    store=Store(str(tmp_path/'bars.db'))
    req=DataRequest(provider='demo',symbol='X',timeframe='1d',start='2024-01-01',end='2024-01-20')
    from unibacktest.model import iso_ms
    t=iso_ms(req.start)
    store.upsert_bars(req.cache_key(),[Bar(t+i*INTERVALS['1d'],100,101,99,100,1) for i in range(10)])
    out=read_candles(req,store,max_points=50)
    assert out['represented_bars']==10
    assert out['display_points']==10
    assert all(x['n_bars']==1 for x in out['candles'])


def test_preview_large_synthetic_no_visual_cutoff():
    from unibacktest.chart import preview_candles
    candles=[Bar(i*60000,100,110 if i==8500 else 102,90 if i==14300 else 99,100,1)
             for i in range(20000)]
    out=preview_candles(candles,900)
    assert len(out)<=900
    assert sum(x['n_bars'] for x in out)==20000
    assert max(x['high'] for x in out)==110
    assert min(x['low'] for x in out)==90