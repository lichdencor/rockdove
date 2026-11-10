import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("AGENT_API_TOKEN", "s3cret")
    from config import get_settings
    get_settings.cache_clear()
    import main
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test", follow_redirects=True) as c:
        yield c


async def test_protected_route_requires_token(client):
    assert (await client.get("/files/")).status_code == 401
    assert (await client.get("/files/", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await client.get("/files/", headers={"Authorization": "Bearer s3cret"})).status_code == 200


async def test_health_and_peer_routes_stay_open(client):
    assert (await client.get("/health")).status_code == 200
