"""Shared fixtures. One in-memory sqlite db, recreated per test so nothing
leaks between tests — cheap enough at this size that ordering/isolation
matters more than the few extra milliseconds."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app

# StaticPool: a plain :memory: db is a fresh, separate database per
# connection — StaticPool keeps every session on the one connection so
# they all see the same schema and rows.
engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def _override_get_db():
    async with TestSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
async def _reset_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def register(client, username="alice", password="password123"):
    email = f"{username}@example.com"
    resp = await client.post(
        "/api/users",
        json={"username": username, "email": email, "password": password},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def login(client, username="alice", password="password123"):
    resp = await client.post(
        "/api/users/token",
        data={"username": f"{username}@example.com", "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def auth_headers(client, username="alice", password="password123"):
    """Registers (if needed) and logs in, returning ready-to-use headers."""
    resp = await client.post(
        "/api/users",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    if resp.status_code not in (201, 400):
        resp.raise_for_status()
    token = await login(client, username, password)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def alice(client):
    """A second, ready-made user — most tests need at least one identity."""
    return await auth_headers(client, "alice")


@pytest.fixture
async def bob(client):
    """A distinct identity for ownership/authorization checks."""
    return await auth_headers(client, "bob")


BOOK = {
    "title": "Dune",
    "author": "Frank Herbert",
    "genre": "Science Fiction",
    "year": 1965,
    "pages": 412,
    "description": "A desert planet, a spice, a prophecy.",
}


async def create_book(client, headers, **overrides):
    resp = await client.post("/api/books", json={**BOOK, **overrides}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()
