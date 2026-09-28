"""Register -> login -> protected route, plus the failure paths that are
easy to silently break (duplicate username/email, wrong password, no
token, garbage token)."""

from tests.conftest import register


async def test_register_and_fetch_me(client):
    await register(client)
    resp = await client.post(
        "/api/users/token",
        data={"username": "alice@example.com", "password": "password123"},
    )
    token = resp.json()["access_token"]

    me = await client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


async def test_duplicate_username_rejected(client):
    await register(client, username="alice")
    resp = await client.post(
        "/api/users",
        json={"username": "alice", "email": "someone-else@example.com", "password": "password123"},
    )
    assert resp.status_code == 400


async def test_duplicate_email_rejected(client):
    await register(client, username="alice")
    resp = await client.post(
        "/api/users",
        json={"username": "someone-else", "email": "alice@example.com", "password": "password123"},
    )
    assert resp.status_code == 400


async def test_short_password_rejected(client):
    resp = await client.post(
        "/api/users",
        json={"username": "alice", "email": "alice@example.com", "password": "short"},
    )
    assert resp.status_code == 422


async def test_wrong_password_rejected(client):
    await register(client)
    resp = await client.post(
        "/api/users/token",
        data={"username": "alice@example.com", "password": "not-the-password"},
    )
    assert resp.status_code == 401


async def test_protected_route_without_token(client):
    resp = await client.get("/api/users/me")
    assert resp.status_code == 401


async def test_protected_route_with_garbage_token(client):
    resp = await client.get("/api/users/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
