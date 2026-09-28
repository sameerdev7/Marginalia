"""Books is the reference resource: every other router (logs, lists, groups,
posts) reuses the same create/ownership pattern this exercises, so it's
worth testing thoroughly here rather than repeating the full matrix per
resource."""

from tests.conftest import BOOK, create_book


async def test_create_requires_auth(client):
    resp = await client.post("/api/books", json=BOOK)
    assert resp.status_code == 401


async def test_create_and_read_public(client, alice):
    book = await create_book(client, alice)
    resp = await client.get(f"/api/books/{book['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Dune"
    # user_id in the request body is ignored — it's always the token's owner
    assert resp.json()["owner"]["username"] == "alice"


async def test_read_nonexistent_book_404(client):
    resp = await client.get("/api/books/999999")
    assert resp.status_code == 404


async def test_owner_can_update(client, alice):
    book = await create_book(client, alice)
    resp = await client.put(
        f"/api/books/{book['id']}",
        json={**BOOK, "title": "Dune Messiah"},
        headers=alice,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Dune Messiah"


async def test_non_owner_cannot_update(client, alice, bob):
    book = await create_book(client, alice)
    resp = await client.put(
        f"/api/books/{book['id']}",
        json={**BOOK, "title": "Hijacked"},
        headers=bob,
    )
    assert resp.status_code == 403


async def test_non_owner_cannot_delete(client, alice, bob):
    book = await create_book(client, alice)
    resp = await client.delete(f"/api/books/{book['id']}", headers=bob)
    assert resp.status_code == 403


async def test_owner_can_delete(client, alice):
    book = await create_book(client, alice)
    resp = await client.delete(f"/api/books/{book['id']}", headers=alice)
    assert resp.status_code == 200
    assert (await client.get(f"/api/books/{book['id']}")).status_code == 404


async def test_similar_books_ranks_by_content(client, alice):
    target = await create_book(client, alice, title="Dune", genre="Science Fiction")
    close = await create_book(
        client, alice, title="Dune Messiah", genre="Science Fiction",
        description="A desert planet, a spice, a prophecy.",
    )
    far = await create_book(
        client, alice, title="Pride and Prejudice", genre="Romance",
        author="Jane Austen", description="Regency manners and marriage.",
    )

    resp = await client.get(f"/api/books/{target['id']}/similar")
    assert resp.status_code == 200
    ids = [b["id"] for b in resp.json()]
    assert target["id"] not in ids  # never recommends itself
    assert close["id"] in ids
    # far shares no vocabulary with target at all, so on a corpus this small
    # it scores exactly 0 and the endpoint drops it rather than padding the
    # list with an unrelated match.
    assert far["id"] not in ids


async def test_similar_books_404_for_missing_book(client):
    resp = await client.get("/api/books/999999/similar")
    assert resp.status_code == 404
