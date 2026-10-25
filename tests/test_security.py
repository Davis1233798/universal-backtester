from fastapi.testclient import TestClient
from unibacktest.api import app


def test_no_secret_locks_every_private_api(monkeypatch):
    monkeypatch.delenv("UBT_PUBLIC_DEMO", raising=False)
    monkeypatch.delenv("UBT_API_TOKEN", raising=False)
    client=TestClient(app)
    assert client.get("/api/health").status_code==200
    for method,path in [
        ("GET","/api/sources"),
        ("GET","/api/markets?provider=ccxt&q=BTC"),
        ("GET","/api/backtests"),("GET","/api/jobs"),
        ("POST","/api/backtests"),("POST","/api/backtests/batch"),
        ("POST","/api/portfolio/backtests"),("POST","/api/jobs")
    ]:
        got=client.request(method,path,json={} if method=="POST" else None)
        assert got.status_code==503,(method,path,got.text)
    assert client.get("/docs").status_code==404
    assert client.get("/openapi.json").status_code==404


def test_private_api_rejects_short_token_and_unauthorized_bearer(monkeypatch):
    monkeypatch.delenv("UBT_PUBLIC_DEMO",raising=False)
    client=TestClient(app)
    monkeypatch.setenv("UBT_API_TOKEN","short")
    assert client.get("/api/sources").status_code==503
    expected="long-nonproduction-secret-for-unit-tests-12345"
    monkeypatch.setenv("UBT_API_TOKEN",expected)
    assert client.get("/api/sources").status_code==401
    assert client.get("/api/sources",headers={"Authorization":"Bearer incorrect"}).status_code==401
    authorized=client.get("/api/sources",headers={"Authorization":"Bearer "+expected})
    assert authorized.status_code==200,authorized.text
    assert authorized.headers["cache-control"]=="no-store"


def test_public_demo_explicitly_allows_only_synthetic(monkeypatch):
    monkeypatch.setenv("UBT_PUBLIC_DEMO","1")
    monkeypatch.delenv("UBT_API_TOKEN",raising=False)
    client=TestClient(app)
    assert client.get("/api/sources").json()["providers"]==["demo"]
    for method,path in [
        ("GET","/api/backtests"),("GET","/api/jobs"),
        ("GET","/api/markets?provider=ccxt&q=BTC"),
        ("POST","/api/backtests/batch"),
        ("POST","/api/portfolio/backtests"),("POST","/api/jobs")
    ]:
        assert client.request(method,path,json={} if method=="POST" else None).status_code==403,path
    run=client.post("/api/backtests",json={
        "data":{"provider":"demo","symbol":"TEST","start":"2024-01-01","end":"2024-02-01"},
        "risk":{"product_type":"spot"},
        "strategy":{"type":"builtin","name":"buy_hold"}
    })
    assert run.status_code==200,run.text
    assert run.json()["run_id"]=="demo-not-saved"
    page=client.get("/").text
    assert ('id="root"' in page or 'id="authToken"' in page)
    assert "unpkg.com" not in page
