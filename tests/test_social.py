"""One happy path plus the one or two guard rails that actually matter per
resource (duplicate constraints, ownership, self-referential edge cases).
Books already exercises the full CRUD/ownership matrix in depth — these all
reuse that same pattern, so they're checked lightly rather than repeated in
full."""

from tests.conftest import create_book


async def _user_id(client, headers):
    return (await client.get("/api/users/me", headers=headers)).json()["id"]


# --- Follows ---------------------------------------------------------------

async def test_follow_unfollow_and_feed(client, alice, bob):
    bob_id = await _user_id(client, bob)
    resp = await client.post(f"/api/users/{bob_id}/follow", headers=alice)
    assert resp.status_code == 201

    book = await create_book(client, bob)
    await client.post("/api/logs", json={"book_id": book["id"], "status": "read"}, headers=bob)

    feed = await client.get("/api/logs/feed", headers=alice)
    assert feed.status_code == 200
    assert any(entry["book_id"] == book["id"] for entry in feed.json())

    assert (await client.delete(f"/api/users/{bob_id}/follow", headers=alice)).status_code == 200


async def test_cannot_follow_self(client, alice):
    alice_id = await _user_id(client, alice)
    resp = await client.post(f"/api/users/{alice_id}/follow", headers=alice)
    assert resp.status_code == 400


async def test_duplicate_follow_blocked(client, alice, bob):
    bob_id = await _user_id(client, bob)
    await client.post(f"/api/users/{bob_id}/follow", headers=alice)
    resp = await client.post(f"/api/users/{bob_id}/follow", headers=alice)
    assert resp.status_code == 400


# --- Reading logs, comments, likes ------------------------------------------

async def test_log_comment_thread_and_like(client, alice, bob):
    book = await create_book(client, alice)
    log = (
        await client.post(
            "/api/logs",
            json={"book_id": book["id"], "status": "read", "rating": 4.5, "review_text": "Loved it."},
            headers=alice,
        )
    ).json()

    parent = (
        await client.post(f"/api/logs/{log['id']}/comments", json={"body": "Agreed!"}, headers=bob)
    ).json()
    reply = await client.post(
        f"/api/logs/{log['id']}/comments",
        json={"body": "Right?", "parent_id": parent["id"]},
        headers=alice,
    )
    assert reply.status_code == 201
    assert reply.json()["parent_id"] == parent["id"]

    assert (await client.post(f"/api/logs/{log['id']}/like", headers=bob)).status_code == 201
    assert (await client.post(f"/api/logs/{log['id']}/like", headers=bob)).status_code == 400
    likes = await client.get(f"/api/logs/{log['id']}/likes")
    assert [u["username"] for u in likes.json()] == ["bob"]


async def test_non_owner_cannot_edit_log(client, alice, bob):
    book = await create_book(client, alice)
    log = (
        await client.post("/api/logs", json={"book_id": book["id"], "status": "read"}, headers=alice)
    ).json()
    resp = await client.patch(f"/api/logs/{log['id']}", json={"status": "dnf"}, headers=bob)
    assert resp.status_code == 403


# --- Lists -------------------------------------------------------------------

async def test_create_list_add_item_and_block_duplicate(client, alice):
    book = await create_book(client, alice)
    lst = (
        await client.post("/api/lists", json={"title": "Favorites", "is_ranked": True}, headers=alice)
    ).json()

    item = await client.post(
        f"/api/lists/{lst['id']}/items",
        json={"book_id": book["id"], "position": 1},
        headers=alice,
    )
    assert item.status_code == 201

    dup = await client.post(
        f"/api/lists/{lst['id']}/items",
        json={"book_id": book["id"], "position": 2},
        headers=alice,
    )
    assert dup.status_code == 400


async def test_cannot_add_item_to_someone_elses_list(client, alice, bob):
    book = await create_book(client, alice)
    lst = (await client.post("/api/lists", json={"title": "Alice's List"}, headers=alice)).json()
    resp = await client.post(
        f"/api/lists/{lst['id']}/items",
        json={"book_id": book["id"], "position": 1},
        headers=bob,
    )
    assert resp.status_code == 403


# --- Groups & posts ----------------------------------------------------------

async def test_group_create_makes_owner_a_member(client, alice):
    group = (
        await client.post("/api/groups", json={"name": "Sci-Fi Club"}, headers=alice)
    ).json()
    members = await client.get(f"/api/groups/{group['id']}/members")
    roles = {m["user"]["username"]: m["role"] for m in members.json()}
    assert roles == {"alice": "owner"}


async def test_join_post_and_owner_cannot_leave(client, alice, bob):
    group = (await client.post("/api/groups", json={"name": "Sci-Fi Club"}, headers=alice)).json()

    assert (await client.post(f"/api/groups/{group['id']}/members", headers=bob)).status_code == 201
    assert (await client.post(f"/api/groups/{group['id']}/members", headers=bob)).status_code == 400

    post = await client.post(
        f"/api/groups/{group['id']}/posts", json={"body": "Reading Dune this month."}, headers=bob,
    )
    assert post.status_code == 201

    assert (await client.delete(f"/api/groups/{group['id']}/members/me", headers=alice)).status_code == 400
    assert (await client.delete(f"/api/groups/{group['id']}/members/me", headers=bob)).status_code == 200


async def test_popular_among_friends(client, alice, bob):
    """Only followed readers count; a book logged twice by one friend is one reader."""
    from tests.conftest import auth_headers

    carol = await auth_headers(client, "carol")
    book = await create_book(client, bob)

    for who in (bob, carol):
        await client.post("/api/logs", json={"book_id": book["id"], "status": "read"}, headers=who)
    await client.post("/api/logs", json={"book_id": book["id"], "status": "read"}, headers=bob)

    # Alice follows nobody yet: nothing to show.
    assert (await client.get("/api/logs/friends/popular", headers=alice)).json() == []

    for who in (bob, carol):
        who_id = await _user_id(client, who)
        await client.post(f"/api/users/{who_id}/follow", headers=alice)

    items = (await client.get("/api/logs/friends/popular", headers=alice)).json()
    assert len(items) == 1
    assert items[0]["book"]["id"] == book["id"]
    assert items[0]["readers"] == 2
    assert {f["username"] for f in items[0]["friends"]} == {"bob", "carol"}

    assert (await client.get("/api/logs/friends/popular")).status_code == 401
