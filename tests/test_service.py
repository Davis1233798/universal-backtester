from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import shutil
import json
import pytest
from unibacktest.adapters import fetch
from unibacktest.model import DataRequest
from unibacktest.service import execute
from unibacktest.scheduler import run_due_jobs
from unibacktest.storage import Store
from unibacktest.strategies import create_strategy


def config():
    return {'data':{'provider':'demo','symbol':'TEST','start':'2024-01-01','end':'2025-01-01'},
            'strategy':{'type':'builtin','name':'sma_cross','options':{'fast':5,'slow':20}},
            'risk':{'product_type':'spot','leverage':1}}


def test_sqlite_cache_and_run(tmp_path):
    store=Store(str(tmp_path/'test.db'))
    r=execute(config(),store)
    assert r['metrics']['closed_trades']>=1
    assert store.get_run(r['run_id'])['result']['bars']>350
    r2=execute(config(),store)
    assert r2['coverage']['newly_fetched_bars']==0
    assert store.list_runs()[0]['id'] in (r['run_id'],r2['run_id'])


def test_scheduler_exactly_once_per_day(tmp_path):
    store=Store(str(tmp_path/'jobs.db'))
    job=store.add_job(config())
    at=datetime(2026,10,24,9,0,tzinfo=timezone.utc)
    assert run_due_jobs(store,datetime(2026,10,23,23,59,tzinfo=timezone.utc)) == []
    one=run_due_jobs(store,at)
    assert len(one)==1 and one[0]['result'].startswith('ok:')
    assert run_due_jobs(store,at)==[]


def test_csv_and_signal_strategy(tmp_path):
    candles=tmp_path/'bars.csv'
    candles.write_text('ts,open,high,low,close,volume,funding_rate\n'
      '1704067200000,100,102,99,101,1,0\n'
      '1704153600000,101,105,100,104,1,0.01\n'
      '1704240000000,104,107,102,106,1,0\n',encoding='utf-8')
    sig=tmp_path/'signals.csv'
    sig.write_text('ts,target\n1704067200000,1\n',encoding='utf-8')
    c={'data':{'provider':'csv','csv_path':str(candles),'start':'2024-01-01','end':'2024-01-04'},
       'strategy':{'type':'signal_csv','path':str(sig)},
       'risk':{'product_type':'perp','fee_bps':0,'slippage_bps':0}}
    r=execute(c,Store(str(tmp_path/'test.db')))
    assert r['bars']==3
    assert r['funding_data_points']==1
    assert r['fills'][0]['ts']==1704153600000


def test_bad_provider_raises():
    with pytest.raises(ValueError):
        fetch(DataRequest(provider='fake'))


def test_external_strategy_must_be_opted_in(monkeypatch):
    monkeypatch.delenv('UBT_ALLOW_EXEC', raising=False)
    with pytest.raises(PermissionError):
        create_strategy({'type':'process','command':['node','x.js']})


def test_node_json_lines(tmp_path,monkeypatch):
    if not shutil.which('node'):pytest.skip('Node not installed')
    monkeypatch.setenv('UBT_ALLOW_EXEC','1')
    script=Path(__file__).resolve().parents[1]/'examples'/'javascript_strategy.mjs'
    st=create_strategy({'type':'process','command':['node',str(script)]})
    try:
        value=st({'bars':[{'close':100} for _ in range(25)], 'target':0})
        assert value==0.0
    finally:st.close()
