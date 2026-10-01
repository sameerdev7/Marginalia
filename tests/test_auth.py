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


# --- forgot / reset password -------------------------------------------------

import re

from sqlalchemy import select

import models
from tests.conftest import TestSessionLocal


async def _issue_token(client, monkeypatch, email="alice@example.com"):
    """Request a reset and capture the emailed token instead of sending mail."""
    sent = {}

    async def fake_send(to, subject, text, html=None):
        sent["to"], sent["text"] = to, text

    monkeypatch.setattr("routers.users.send_email", fake_send)
    resp = await client.post("/api/users/forgot-password", json={"email": email})
    assert resp.status_code == 202
    match = re.search(r"token=([\w-]+)", sent.get("text", ""))
    return match.group(1) if match else None


async def test_forgot_password_does_not_reveal_unknown_email(client, monkeypatch):
    token = await _issue_token(client, monkeypatch, email="nobody@example.com")
    assert token is None  # same 202, but no email was queued


async def test_reset_password_flow(client, monkeypatch):
    await register(client)
    token = await _issue_token(client, monkeypatch)
    assert token

    resp = await client.post(
        "/api/users/reset-password", json={"token": token, "password": "brand-new-pass"}
    )
    assert resp.status_code == 200

    old = await client.post(
        "/api/users/token", data={"username": "alice@example.com", "password": "password123"}
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/users/token", data={"username": "alice@example.com", "password": "brand-new-pass"}
    )
    assert new.status_code == 200


async def test_reset_token_is_single_use(client, monkeypatch):
    await register(client)
    token = await _issue_token(client, monkeypatch)
    body = {"token": token, "password": "brand-new-pass"}
    assert (await client.post("/api/users/reset-password", json=body)).status_code == 200
    assert (await client.post("/api/users/reset-password", json=body)).status_code == 400


async def test_new_request_voids_earlier_link(client, monkeypatch):
    await register(client)
    first = await _issue_token(client, monkeypatch)
    await _issue_token(client, monkeypatch)
    resp = await client.post(
        "/api/users/reset-password", json={"token": first, "password": "brand-new-pass"}
    )
    assert resp.status_code == 400


async def test_expired_token_rejected(client, monkeypatch):
    from datetime import UTC, datetime, timedelta

    await register(client)
    token = await _issue_token(client, monkeypatch)
    async with TestSessionLocal() as db:
        grant = (await db.execute(select(models.PasswordResetToken))).scalars().first()
        grant.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    resp = await client.post(
        "/api/users/reset-password", json={"token": token, "password": "brand-new-pass"}
    )
    assert resp.status_code == 400


async def test_garbage_token_rejected(client):
    resp = await client.post(
        "/api/users/reset-password", json={"token": "x" * 30, "password": "brand-new-pass"}
    )
    assert resp.status_code == 400
