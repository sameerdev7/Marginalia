"""Journal: drafts are private, publishing is public, edits are owner-only."""

from tests.conftest import create_book

ENTRY = {"title": "On Margins", "body": "## Hello\n\nA *short* essay about **notes**.", "published": True}


async def _post(client, headers, **overrides):
    resp = await client.post("/api/journal", json={**ENTRY, **overrides}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_publish_and_read_publicly(client, alice):
    entry = await _post(client, alice)
    assert entry["published_at"] is not None
    assert entry["reading_minutes"] == 1

    public = await client.get(f"/api/journal/{entry['id']}")  # no token
    assert public.status_code == 200
    assert public.json()["author"]["username"] == "alice"

    listing = await client.get("/api/journal")
    assert [e["id"] for e in listing.json()] == [entry["id"]]
    assert "body" not in listing.json()[0]
    assert listing.json()[0]["excerpt"].startswith("Hello")


async def test_draft_is_private_to_author(client, alice, bob):
    draft = await _post(client, alice, published=False)
    assert draft["published_at"] is None

    assert (await client.get(f"/api/journal/{draft['id']}")).status_code == 404
    assert (await client.get(f"/api/journal/{draft['id']}", headers=bob)).status_code == 404
    assert (await client.get(f"/api/journal/{draft['id']}", headers=alice)).status_code == 200

    assert (await client.get("/api/journal")).json() == []
    mine = await client.get("/api/journal/mine", headers=alice)
    assert [e["id"] for e in mine.json()] == [draft["id"]]
    assert (await client.get("/api/journal/mine", headers=bob)).json() == []


async def test_publish_later_stamps_date(client, alice):
    draft = await _post(client, alice, published=False)
    resp = await client.patch(f"/api/journal/{draft['id']}", json={"published": True}, headers=alice)
    assert resp.status_code == 200
    assert resp.json()["published_at"] is not None
    assert len((await client.get("/api/journal")).json()) == 1


async def test_only_owner_can_edit_or_delete(client, alice, bob):
    entry = await _post(client, alice)
    url = f"/api/journal/{entry['id']}"
    assert (await client.patch(url, json={"title": "Hijacked"}, headers=bob)).status_code == 403
    assert (await client.delete(url, headers=bob)).status_code == 403
    assert (await client.patch(url, json={"title": "Mine"})).status_code == 401

    assert (await client.patch(url, json={"title": "Better"}, headers=alice)).json()["title"] == "Better"
    assert (await client.delete(url, headers=alice)).status_code == 204
    assert (await client.get(url)).status_code == 404


async def test_link_a_book_and_filter(client, alice):
    book = await create_book(client, alice)
    entry = await _post(client, alice, book_id=book["id"])
    assert entry["book"]["title"] == "Dune"

    assert len((await client.get(f"/api/journal?book_id={book['id']}")).json()) == 1
    assert (await client.get("/api/journal?book_id=999")).json() == []

    bad = await client.post("/api/journal", json={**ENTRY, "book_id": 999}, headers=alice)
    assert bad.status_code == 404


async def test_validation_and_auth(client, alice):
    assert (await client.post("/api/journal", json=ENTRY)).status_code == 401
    empty = await client.post("/api/journal", json={**ENTRY, "title": ""}, headers=alice)
    assert empty.status_code == 422
