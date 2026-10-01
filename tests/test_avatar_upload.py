"""Avatar upload: format sniffing, size limit, file replacement, auth."""

import base64

import pytest

import routers.users as users_router

# 1x1 PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def _tmp_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(users_router, "AVATAR_DIR", tmp_path / "avatars")
    return tmp_path / "avatars"


async def test_upload_sets_avatar_and_stores_file(client, alice, _tmp_upload_dir):
    resp = await client.post("/api/users/me/avatar", files={"file": ("me.png", PNG, "image/png")}, headers=alice)
    assert resp.status_code == 200
    url = resp.json()["avatar_url"]
    assert url.startswith("/api/uploads/avatars/") and url.endswith(".png")
    assert (_tmp_upload_dir / url.rsplit("/", 1)[-1]).exists()


async def test_replacing_deletes_the_old_file(client, alice, _tmp_upload_dir):
    first = await client.post("/api/users/me/avatar", files={"file": ("a.png", PNG, "image/png")}, headers=alice)
    second = await client.post("/api/users/me/avatar", files={"file": ("b.png", PNG, "image/png")}, headers=alice)
    assert first.json()["avatar_url"] != second.json()["avatar_url"]
    assert len(list(_tmp_upload_dir.iterdir())) == 1


async def test_content_is_sniffed_not_trusted(client, alice):
    resp = await client.post(
        "/api/users/me/avatar", files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")}, headers=alice
    )
    assert resp.status_code == 400


async def test_size_limit(client, alice):
    big = PNG + b"0" * (users_router.MAX_AVATAR_BYTES + 10)
    resp = await client.post("/api/users/me/avatar", files={"file": ("big.png", big, "image/png")}, headers=alice)
    assert resp.status_code == 413


async def test_upload_requires_auth(client):
    resp = await client.post("/api/users/me/avatar", files={"file": ("me.png", PNG, "image/png")})
    assert resp.status_code == 401
