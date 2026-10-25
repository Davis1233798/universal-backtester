import pytest

@pytest.fixture(autouse=True)
def test_only_api_token(monkeypatch):
    monkeypatch.setenv("UBT_API_TOKEN","test-only-not-a-production-secret-0123456789")
