import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "storage"))
    from config import get_settings
    get_settings.cache_clear()
    from fastapi import FastAPI
    from files.router import router
    app = FastAPI()
    app.include_router(router, prefix="/files")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True) as c:
        yield c
    get_settings.cache_clear()


async def test_upload_returns_metadata(client):
    r = await client.post(
        "/files",
        files={"file": ("hello.txt", b"hello content", "text/plain")},
    )
    assert r.status_code == 200
    meta = r.json()
    assert meta["filename"] == "hello.txt"
    assert meta["size"] == 13
    assert len(meta["sha256"]) == 64
    assert "file_id" in meta


async def test_list_includes_uploaded_file(client):
    r = await client.post("/files", files={"file": ("a.txt", b"abc", "text/plain")})
    file_id = r.json()["file_id"]

    r = await client.get("/files")
    assert r.status_code == 200
    ids = [f["file_id"] for f in r.json()]
    assert file_id in ids


async def test_get_meta(client):
    r = await client.post("/files", files={"file": ("m.bin", b"binary", "application/octet-stream")})
    file_id = r.json()["file_id"]

    r = await client.get(f"/files/{file_id}/meta")
    assert r.status_code == 200
    assert r.json()["file_id"] == file_id


async def test_download_returns_original_bytes(client):
    data = b"download me please"
    r = await client.post("/files", files={"file": ("dl.bin", data, "application/octet-stream")})
    file_id = r.json()["file_id"]

    r = await client.get(f"/files/{file_id}")
    assert r.status_code == 200
    assert r.content == data


async def test_delete_removes_file(client):
    r = await client.post("/files", files={"file": ("del.txt", b"bye", "text/plain")})
    file_id = r.json()["file_id"]

    r = await client.delete(f"/files/{file_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] == file_id

    r = await client.get(f"/files/{file_id}/meta")
    assert r.status_code == 404


async def test_404_on_missing_meta(client):
    assert (await client.get("/files/nonexistent/meta")).status_code == 404


async def test_404_on_missing_download(client):
    assert (await client.get("/files/nonexistent")).status_code == 404


async def test_404_on_missing_delete(client):
    assert (await client.delete("/files/nonexistent")).status_code == 404


async def test_upload_over_limit_is_rejected(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "10")
    from config import get_settings
    get_settings.cache_clear()
    r = await client.post("/files", files={"file": ("big.bin", b"x" * 11, "application/octet-stream")})
    assert r.status_code == 413
    ok = await client.post("/files", files={"file": ("ok.bin", b"x" * 10, "application/octet-stream")})
    assert ok.status_code == 200
