"""AI draft integration: auth boundary, no-provider fallback, parsed output."""
import asyncio
from fastapi.testclient import TestClient
from unibacktest.api import app
from unibacktest.ai import generate_pine


def test_ai_generation_private_fail_closed(monkeypatch):
    client=TestClient(app)
    monkeypatch.setenv("UBT_PUBLIC_DEMO","1")
    assert client.post("/api/strategies/generate",json={"description":"Create a moving average strategy"}).status_code==403
    monkeypatch.setenv("UBT_PUBLIC_DEMO","0")
    monkeypatch.setenv("UBT_API_TOKEN","a-test-token-long-enough-for-fixtures-012345")
    monkeypatch.delenv("UBT_AI_API_KEY",raising=False)
    assert client.post("/api/strategies/generate",json={"description":"Create a moving average strategy"}).status_code==401
    response=client.post("/api/strategies/generate",json={"description":"Create a moving average strategy"},
        headers={"Authorization":"Bearer a-test-token-long-enough-for-fixtures-012345"})
    assert response.status_code==503
    assert "UBT_AI_API_KEY" in response.text


def test_ai_response_must_parse_and_is_not_saved(monkeypatch):
    import unibacktest.ai as ai
    code='//@version=6\nstrategy("SMA")\nif close > open\n    strategy.entry("L", strategy.long)'
    calls=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {"choices":[{"message":{"content":"```pine\n"+code+"\n```"}}]}
    class FakeClient:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def post(self,url,**kwargs):calls.append((url,kwargs));return Response()
    monkeypatch.setattr(ai.httpx,"AsyncClient",FakeClient)
    monkeypatch.setenv("UBT_AI_API_KEY","private-test-token")
    out=asyncio.run(generate_pine("Build a basic bullish momentum entry"))
    assert out["validated_subset"] is True
    assert out["code"]==code
    assert calls[0][0]=="https://api.openai.com/v1/chat/completions"
    assert calls[0][1]["headers"]["Authorization"]=="Bearer private-test-token"
