from fastapi.testclient import TestClient
from unibacktest.api import app
from unibacktest.storage import Store
from unibacktest.library import save_strategy,list_strategies,revisions,restore_revision

SAMPLE='''//@version=6\nstrategy("Test")\nif close > open\n    strategy.entry("Long",strategy.long)\n'''


def test_library_create_update_restore_delete(tmp_path):
    store=Store(str(tmp_path/'library.sqlite3'))
    draft={"name":"EMA Research","kind":"pine","code":SAMPLE,"options":{}}
    a=save_strategy(store,draft)
    assert a['revision']==1
    assert a['kind']=='pine'
    assert len(list_strategies(store))==1
    b=save_strategy(store,{**draft,'name':'EMA Research 2'},a['id'])
    assert b['revision']==2
    history=revisions(store,a['id'])
    assert [x['revision'] for x in history]==[2,1]
    c=restore_revision(store,a['id'],1)
    assert c['revision']==3 and c['name']=='EMA Research'
    from unibacktest.library import delete_strategy
    assert delete_strategy(store,a['id'])
    assert list_strategies(store)==[]


def test_library_requires_private_auth(monkeypatch,tmp_path):
    monkeypatch.setenv('UBT_PUBLIC_DEMO','1')
    c=TestClient(app)
    assert c.get('/api/strategies').status_code==403
    monkeypatch.setenv('UBT_PUBLIC_DEMO','0')
    monkeypatch.delenv('UBT_API_TOKEN',raising=False)
    assert c.get('/api/strategies').status_code==503
    monkeypatch.setenv('UBT_API_TOKEN','unit-test-token-not-valid-in-production-123456')
    assert c.get('/api/strategies').status_code==401
    import unibacktest.storage as storage
    monkeypatch.setattr(storage,'DEFAULT_DB',str(tmp_path/'api.sqlite3'))
    client=TestClient(app,headers={'Authorization':'Bearer unit-test-token-not-valid-in-production-123456'})
    create=client.post('/api/strategies',json={'name':'Test','kind':'pine','code':SAMPLE,'options':{}})
    assert create.status_code==200,create.text
    sid=create.json()['id']
    assert client.get('/api/strategies').json()[0]['id']==sid
    assert client.get(f'/api/strategies/{sid}/revisions').json()[0]['revision']==1
    assert client.put(f'/api/strategies/{sid}',json={'name':'Test 2','kind':'pine','code':SAMPLE,'options':{}}).json()['revision']==2
    assert client.post(f'/api/strategies/{sid}/restore/1').json()['revision']==3
    assert client.delete(f'/api/strategies/{sid}').status_code==200
    assert client.get('/api/strategies').json()==[]


def test_strategy_save_rejects_unsupported_pine(tmp_path):
    import pytest
    store=Store(str(tmp_path/'bad.sqlite3'))
    with pytest.raises(ValueError):
        save_strategy(store,{'name':'bad','kind':'pine','code':'strategy("X")\nstrategy.cancel("a")','options':{}})