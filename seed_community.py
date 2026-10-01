"""Seed a believable community and smoke-test every user-facing feature.

Unlike seed_books.py / seed_activity.py, which write rows straight into the
database, this drives the app's real HTTP API in-process (httpx + ASGI
transport) *as the users*. Every record it creates therefore went through the
same validation, auth and ownership checks a browser request would — so the
run doubles as an end-to-end test, and prints a PASS/FAIL checklist at the end.

What it does
  1. Gives every reader a real photo avatar (randomuser.me portraits) and the
     library account the Athenaeum temple mark.
  2. Registers six new readers, sets their avatars through PATCH, and lets
     them (and the existing readers) follow each other, log books with
     reviews, comment and reply, like, build lists, write journal entries,
     edit and delete things, and reset a forgotten password.
  3. Probes the permission edges (403/401/404) and the read endpoints.
  4. Back-dates the new activity over the last few weeks so feeds look lived-in.

Groups, chat and audio are deliberately untouched (tested live, by hand).

Idempotent: if the first new reader already exists the content phase is
skipped and only the read-only checks run.

    uv run python seed_community.py
"""

import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update

import models
from database import SessionLocal
from main import app

DEMO_PASSWORD = "vellum-2024"  # same demo password seed_activity.py uses
PORTRAIT = "https://randomuser.me/api/portraits/{}.jpg"

# Existing readers -> portrait. (Left alone on purpose: the real "travis" account.)
EXISTING_PORTRAITS = {
    "mara_linden": "women/44",
    "theo_baptiste": "men/22",
    "priya_raman": "women/68",
    "elin_oseberg": "women/12",
    "jonah_whitfield": "men/46",
    "naomi_okonkwo": "women/79",
    "felix_hartmann": "men/75",
    "ines_marchetti": "women/33",
    "rowan_boyle": "men/54",
    "tamsin_ellery": "women/21",
}

# The Athenaeum mark as a compact data URI (fits the 500-char avatar column).
LIBRARY_AVATAR = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Crect width='64' height='64' rx='14' fill='%23dcb056'/%3E"
    "%3Cpath d='M10 25 32 12l22 13M16 28v19M26.5 28v19M37.5 28v19M48 28v19M9 53h46' "
    "fill='none' stroke='%231d1409' stroke-width='4.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"
)

# (username, portrait, [(book, status, rating, review)])
NEW_READERS = [
    ("lucia_ferreira", "women/57", [
        ("One Hundred Years of Solitude", "read", 5.0, "I kept a family tree on the back page and it still wasn't enough. Worth every confused minute."),
        ("Love in the Time of Cholera", "read", 4.5, "A love story told across fifty years. The patience is the entire point."),
        ("Piranesi", "read", 5.0, "The smallest, strangest, kindest book I read this year."),
        ("The Name of the Rose", "reading", None, None),
    ]),
    ("amir_haddad", "men/36", [
        ("Dune", "read", 4.5, "The politics are the plot. Read the appendices; they're doing more work than you think."),
        ("The Three-Body Problem", "read", 4.0, "Big ideas first, characters second, and I'm fine with that trade."),
        ("Sapiens", "read", 3.5, "Provocative, readable, and a little too sure of itself."),
        ("Neuromancer", "want_to_read", None, None),
    ]),
    ("sofia_lindqvist", "women/26", [
        ("And Then There Were None", "read", 5.0, "A perfect machine. I tried to outguess it on every page and lost every time."),
        ("Rebecca", "read", 4.5, "Never names its narrator and never needs to. Manderley is the real character."),
        ("Gone Girl", "dnf", 2.5, "Admired the construction, couldn't spend another chapter with these two."),
        ("The Silent Patient", "reading", None, None),
    ]),
    ("kenji_watanabe", "men/61", [
        ("Norwegian Wood", "read", 4.0, "Quiet and melancholy in a way that sneaks up on you around page 200."),
        ("Klara and the Sun", "read", 4.5, "Gentle, then devastating. Ishiguro doing what only Ishiguro does."),
        ("Moby-Dick", "dnf", 3.0, "Lost the thread somewhere in the whaling chapters. I'll try again in winter."),
        ("Never Let Me Go", "want_to_read", None, None),
    ]),
    ("dara_okafor", "women/85", [
        ("Homegoing", "read", 5.0, "Every chapter is a life; together they're a century. Unforgettable."),
        ("Wolf Hall", "read", 4.0, "Mantel makes you root for Cromwell, then feel bad about it."),
        ("Beloved", "read", 5.0, "I had to put it down and walk around the block twice."),
        ("The Warmth of Other Suns", "reading", None, None),
    ]),
    ("callum_reyes", "men/15", [
        ("The Hobbit", "read", 4.0, "Still the coziest adventure ever written. Second breakfast forever."),
        ("Mistborn", "read", 4.5, "The magic system is a puzzle and the ending is the payoff."),
        ("The Hunger Games", "read", 4.0, "Fast, grim and smarter than its reputation."),
        ("Circe", "read", 4.5, "Gorgeous and angry. The prose carries you straight through."),
    ]),
]

# Who each new reader follows (existing + new).
FOLLOWS = {
    "lucia_ferreira": ["mara_linden", "tamsin_ellery", "elin_oseberg", "dara_okafor", "kenji_watanabe", "athenaeum_library"],
    "amir_haddad": ["jonah_whitfield", "felix_hartmann", "ines_marchetti", "callum_reyes", "athenaeum_library"],
    "sofia_lindqvist": ["priya_raman", "theo_baptiste", "rowan_boyle", "lucia_ferreira"],
    "kenji_watanabe": ["tamsin_ellery", "naomi_okonkwo", "mara_linden", "lucia_ferreira", "dara_okafor"],
    "dara_okafor": ["naomi_okonkwo", "elin_oseberg", "lucia_ferreira", "kenji_watanabe", "theo_baptiste"],
    "callum_reyes": ["felix_hartmann", "amir_haddad", "rowan_boyle", "jonah_whitfield"],
}
# Existing readers who follow some newcomers back.
FOLLOWED_BACK = {
    "mara_linden": ["lucia_ferreira", "kenji_watanabe"],
    "tamsin_ellery": ["lucia_ferreira", "kenji_watanabe", "dara_okafor"],
    "jonah_whitfield": ["amir_haddad", "callum_reyes"],
    "priya_raman": ["sofia_lindqvist"],
    "theo_baptiste": ["sofia_lindqvist", "dara_okafor"],
    "felix_hartmann": ["callum_reyes", "amir_haddad"],
    "naomi_okonkwo": ["dara_okafor", "kenji_watanabe"],
}

LISTS = {
    "lucia_ferreira": ("Magical Realism, Ranked", "Books where the impossible is just Tuesday.", True,
                       ["One Hundred Years of Solitude", "Love in the Time of Cholera", "Piranesi", "Beloved", "The Night Circus"]),
    "amir_haddad": ("Hard Ideas, Soft Landings", "Science fiction and science writing that make big concepts feel human.", False,
                    ["Dune", "The Three-Body Problem", "Sapiens", "Children of Time", "The Left Hand of Darkness"]),
    "sofia_lindqvist": ("Mysteries I'd Reread Blind", "Plots so tight I'd happily forget them and start over.", True,
                        ["And Then There Were None", "Rebecca", "The Murder of Roger Ackroyd", "The Big Sleep", "In the Woods"]),
    "kenji_watanabe": ("Quiet Novels for Long Trains", "Slow, spare, and good company across a landscape.", False,
                       ["Norwegian Wood", "Klara and the Sun", "The Remains of the Day", "Never Let Me Go", "Giovanni's Room"]),
    "dara_okafor": ("History You Can Feel", "Nonfiction and fiction that make the past feel like a living room.", False,
                    ["Homegoing", "Wolf Hall", "The Warmth of Other Suns", "Beloved", "The Pillars of the Earth"]),
    "callum_reyes": ("Comfort Fantasy", "For when the world is loud and you want a map.", False,
                     ["The Hobbit", "Mistborn", "Circe", "Uprooted", "The Name of the Wind"]),
}

JOURNAL = {
    "lucia_ferreira": ("Why I Reread One Hundred Years of Solitude Every Spring",
                       "A family tree, a new translation of my own memory, and a book that keeps changing.", "One Hundred Years of Solitude", True,
"""I first read this book at nineteen, on a bus, and understood perhaps a third of it. Every spring since, I have picked it up again, and each time it is a *different book*.

## The family tree trick

Keep a bookmark with the names. There are only so many Aurelianos and José Arcadios, and you will lose track of them anyway.

| Reading | Age | What I noticed |
| --- | --- | --- |
| First | 19 | The magic: yellow butterflies, the rain of flowers |
| Third | 24 | The repetition: names, mistakes, lonely rooms |
| Sixth | 31 | The *time*: how a century folds into a house |

## What changes

- The jokes get funnier.
- The sadness gets heavier.
- You stop asking *is this real?*[^1]

> Many years later, as he faced the firing squad…

The first sentence is a promise the whole book keeps.

[^1]: In Macondo, the question is rude."""),
    "amir_haddad": ("Appendices Are Part of the Book",
                    "Dune's back matter is not a footnote. It is a second argument.", "Dune", True,
"""Most readers stop at the last page of the story. With *Dune* that means skipping a quarter of the book's worldbuilding.

## What the appendices do

1. **The Ecology of Dune** shows the planet's logic before the plot spends it.
2. **The Religion of Dune** reframes the faith as a manufactured tool.
3. **Report on Bene Gesserit Motives and Purposes** tells you who was really playing chess.

## A small checklist

- [x] Read the novel
- [x] Read the appendices
- [ ] Re-read Part One with them in mind

Skipping them is like leaving before the credits of a film that explains the twist."""),
    "kenji_watanabe": ("Reading Slowly on Trains",
                       "Four journeys, four books, and what each pace of reading taught me.", "Norwegian Wood", True,
"""A train changes how you read. The ride gives you a fixed amount of time and a window that keeps moving.

## The rules I follow

- **One book per line.** Don't switch mid-journey.
- **Pencil only.** Pens leak in a bag.
- **Stop at the end of a chapter**, never mid-scene.

## Journeys

| Route | Time | Book |
| --- | --- | --- |
| Morning commute | 40 min | Short essays |
| Weekend line | 2 h | A novel in one sitting |
| Night train | 6 h | Something with a *long* spell |

The best case is arriving in the middle of a sentence, and being glad you did."""),
    "callum_reyes": ("Maps in the Front of Fantasy Books",
                     "Why we trust the maps, and what happens when the plot ignores them.", "The Hobbit", False,
"""Open almost any fantasy novel and the first page is a **map**.

## Why they matter

A map tells you the author has thought about *distance*. A journey across it has weight.

- Good maps make the plot feel earned.
- Bad maps are decoration.

*(Draft: still need an example from Mistborn.)*"""),
    "sofia_lindqvist": ("Notes Toward a Perfect Murder Mystery",
                        "Ten rules, three of which every mystery I love breaks.", "And Then There Were None", False,
"""Draft notes:

1. The detective should be *fair*.
2. The culprit must appear early.
3. No coincidences that only help the author.

> Rule four: the setting is a suspect too."""),
}

# Extra reviews/comment lines to make threads
COMMENT_LINES = [
    "This is exactly how I felt about it. Beautifully put.",
    "I'd put it a notch lower, but I love how you wrote this.",
    "Adding this to my list immediately.",
    "The last line of your review made me laugh.",
    "Did you read the translation or the original? It changes everything.",
    "Disagree on the ending, but I respect the take.",
    "Great pick. Have you tried the author's earlier work?",
    "Saving this for my next reading slump.",
]
REPLY_LINES = [
    "Thank you! It stuck with me for days.",
    "Fair point. I might reread it and see.",
    "The original, but I'd love to hear how the other lands.",
    "Same here, honestly.",
]

REPORT: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    REPORT.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


class Actor:
    def __init__(self, client: httpx.AsyncClient, username: str, password: str = DEMO_PASSWORD):
        self.c, self.username, self.password = client, username, password
        self.headers: dict[str, str] = {}
        self.id: int | None = None

    async def login(self, password: str | None = None) -> None:
        r = await self.c.post(
            "/api/users/token",
            data={"username": f"{self.username}@athenaeum.app".replace("_", "."), "password": password or self.password},
        )
        r.raise_for_status()
        self.headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.id = (await self.c.get("/api/users/me", headers=self.headers)).json()["id"]

    async def req(self, method: str, url: str, **kw) -> httpx.Response:
        return await self.c.request(method, url, headers=self.headers, **kw)


def aware(d: datetime) -> datetime:
    """SQLite hands datetimes back naive; everything here is stored as UTC."""
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def email_of(username: str) -> str:
    return f"{username.replace('_', '.')}@athenaeum.app"


async def main() -> int:
    rng = random.Random(7)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://seed", timeout=60) as c:
        books = {b["title"]: b for b in (await c.get("/api/books")).json()}

        # ---- 1. avatars for existing accounts (direct: we don't hold the library's password)
        async with SessionLocal() as db:
            for name, p in EXISTING_PORTRAITS.items():
                await db.execute(update(models.User).where(models.User.username == name).values(avatar_url=PORTRAIT.format(p)))
            await db.execute(update(models.User).where(models.User.username == "athenaeum_library").values(avatar_url=LIBRARY_AVATAR))
            await db.commit()
        print("Avatars updated for existing readers.")

        exists = (await c.get("/api/users")).json()
        already = any(u["username"] == "lucia_ferreira" for u in exists)

        existing_actors = {n: Actor(c, n) for n in EXISTING_PORTRAITS}
        for a in existing_actors.values():
            await a.login()

        new_actors: dict[str, Actor] = {}
        if not already:
            print("\n== Accounts")
            for username, portrait, _ in NEW_READERS:
                r = await c.post("/api/users", json={"username": username, "email": email_of(username), "password": DEMO_PASSWORD})
                check(f"register {username}", r.status_code == 201, r.text)
                a = Actor(c, username)
                await a.login()
                new_actors[username] = a
                r = await a.req("PATCH", f"/api/users/{a.id}", json={"avatar_url": PORTRAIT.format(portrait)})
                check(f"set avatar {username}", r.status_code == 200 and "randomuser" in r.json()["avatar_url"], r.text)
            dup = await c.post("/api/users", json={"username": "lucia_ferreira", "email": "x@athenaeum.app", "password": DEMO_PASSWORD})
            check("duplicate username rejected", dup.status_code == 400)
            bad = await c.post("/api/users/token", data={"username": email_of("lucia_ferreira"), "password": "wrong-password"})
            check("wrong password rejected", bad.status_code == 401)

            everyone = {**existing_actors, **new_actors}
            ids = {n: a.id for n, a in everyone.items()}
            async with SessionLocal() as db:
                ids["athenaeum_library"] = (await db.execute(select(models.User.id).where(models.User.username == "athenaeum_library"))).scalar_one()

            print("\n== Follows")
            for who, targets in FOLLOWS.items():
                for t in targets:
                    r = await new_actors[who].req("POST", f"/api/users/{ids[t]}/follow")
                    if r.status_code != 201:
                        check(f"{who} follows {t}", False, r.text)
            for who, targets in FOLLOWED_BACK.items():
                for t in targets:
                    await existing_actors[who].req("POST", f"/api/users/{ids[t]}/follow")
            r = await new_actors["lucia_ferreira"].req("GET", f"/api/users/{ids['lucia_ferreira']}/following")
            check("following list populated", len(r.json()) == len(FOLLOWS["lucia_ferreira"]))
            r = await new_actors["lucia_ferreira"].req("POST", f"/api/users/{ids['lucia_ferreira']}/follow")
            check("cannot follow yourself", r.status_code == 400)
            r = await new_actors["kenji_watanabe"].req("DELETE", f"/api/users/{ids['dara_okafor']}/follow")
            check("unfollow", r.status_code == 200)
            await new_actors["kenji_watanabe"].req("POST", f"/api/users/{ids['dara_okafor']}/follow")

            print("\n== Reading logs")
            my_logs: dict[str, list[dict]] = {}
            for username, _, logs in NEW_READERS:
                a = new_actors[username]
                my_logs[username] = []
                for title, status, rating, review in logs:
                    book = books.get(title)
                    if not book:
                        check(f"book exists: {title}", False)
                        continue
                    body = {"book_id": book["id"], "status": status, "rating": rating, "review_text": review}
                    if status == "read":
                        body["finished_at"] = (datetime.now(UTC) - timedelta(days=rng.randint(3, 60))).date().isoformat()
                    if title == "The Hobbit":
                        body["is_reread"] = True
                    r = await a.req("POST", "/api/logs", json=body)
                    if r.status_code != 201:
                        check(f"{username} logs {title}", False, r.text)
                    else:
                        my_logs[username].append(r.json())
            check("reading logs created", sum(len(v) for v in my_logs.values()) == sum(len(l) for _, _, l in NEW_READERS))
            # edit: kenji bumps a rating; callum logs then deletes a temp entry
            k = new_actors["kenji_watanabe"]
            target = next(l for l in my_logs["kenji_watanabe"] if l["rating"] == 4.0)
            r = await k.req("PATCH", f"/api/logs/{target['id']}", json={"rating": 4.5, "review_text": "Quiet and melancholy in a way that sneaks up on you. Rereading confirmed it."})
            check("edit own log", r.status_code == 200 and r.json()["rating"] == 4.5)
            tmp = await new_actors["callum_reyes"].req("POST", "/api/logs", json={"book_id": books["Dune"]["id"], "status": "want_to_read"})
            r = await new_actors["callum_reyes"].req("DELETE", f"/api/logs/{tmp.json()['id']}")
            check("delete own log", r.status_code in (200, 204))
            r = await new_actors["amir_haddad"].req("PATCH", f"/api/logs/{my_logs['lucia_ferreira'][0]['id']}", json={"rating": 1})
            check("cannot edit someone else's log (403)", r.status_code == 403)
            r = await new_actors["amir_haddad"].req("POST", "/api/logs", json={"book_id": 99999, "status": "read"})
            check("log for unknown book rejected (404)", r.status_code == 404)

            print("\n== Comments, replies, likes")
            all_reviews = (await c.get("/api/logs?has_review=true&limit=80")).json()
            by_user: dict[int, list[dict]] = {}
            for l in all_reviews:
                by_user.setdefault(l["user_id"], []).append(l)
            new_ids = {a.id for a in new_actors.values()}
            old_reviews = [l for l in all_reviews if l["user_id"] not in new_ids]
            made_comments = 0
            for a in new_actors.values():
                for l in rng.sample(old_reviews, 3):
                    r = await a.req("POST", f"/api/logs/{l['id']}/comments", json={"body": rng.choice(COMMENT_LINES)})
                    made_comments += r.status_code == 201
            # existing readers comment on newcomers' reviews, newcomers reply
            replies = 0
            for username, logs in my_logs.items():
                for l in [x for x in logs if x["review_text"]][:2]:
                    commenter = existing_actors[rng.choice(list(existing_actors))]
                    r = await commenter.req("POST", f"/api/logs/{l['id']}/comments", json={"body": rng.choice(COMMENT_LINES)})
                    made_comments += r.status_code == 201
                    if r.status_code == 201:
                        rr = await new_actors[username].req(
                            "POST", f"/api/logs/{l['id']}/comments",
                            json={"body": rng.choice(REPLY_LINES), "parent_id": r.json()["id"]},
                        )
                        replies += rr.status_code == 201
            check("comments posted", made_comments >= 20, str(made_comments))
            check("threaded replies posted", replies >= 8, str(replies))
            # comment ownership
            first = (await c.get(f"/api/logs/{my_logs['lucia_ferreira'][0]['id']}/comments")).json()
            if first:
                r = await new_actors["amir_haddad"].req("DELETE", f"/api/comments/{first[0]['id']}")
                check("cannot delete someone else's comment (403)", r.status_code == 403)
            # likes (+ toggle off)
            liked = 0
            pool = old_reviews + [l for ls in my_logs.values() for l in ls if l["review_text"]]
            for a in list(new_actors.values()) + list(existing_actors.values()):
                for l in rng.sample(pool, 9):
                    if l["user_id"] == a.id:
                        continue
                    r = await a.req("POST", f"/api/logs/{l['id']}/like")
                    liked += r.status_code in (200, 201)
            check("likes recorded", liked >= 60, str(liked))
            sample = pool[0]
            ak = new_actors["amir_haddad"]
            await ak.req("POST", f"/api/logs/{sample['id']}/like")
            r = await ak.req("DELETE", f"/api/logs/{sample['id']}/like")
            check("unlike", r.status_code in (200, 204))
            r = await c.post(f"/api/logs/{sample['id']}/like")
            check("like requires sign-in (401)", r.status_code == 401)

            print("\n== Lists")
            for username, (title, desc, ranked, picks) in LISTS.items():
                a = new_actors[username]
                r = await a.req("POST", "/api/lists", json={"title": title, "description": desc, "is_ranked": ranked})
                if r.status_code != 201:
                    check(f"{username} creates list", False, r.text)
                    continue
                lid = r.json()["id"]
                item_ids = []
                for pos, t in enumerate(picks, start=1):
                    b = books.get(t)
                    if not b:
                        continue
                    body = {"book_id": b["id"], "position": pos}
                    if pos == 1:
                        body["note"] = "Start here."
                    ir = await a.req("POST", f"/api/lists/{lid}/items", json=body)
                    if ir.status_code == 201:
                        item_ids.append(ir.json()["id"])
                if username == "lucia_ferreira":
                    r = await a.req("PATCH", f"/api/lists/{lid}", json={"description": desc + " Updated after a spring reread."})
                    check("edit list", r.status_code == 200)
                    r = await a.req("PATCH", f"/api/lists/{lid}/items/{item_ids[2]}", json={"position": 2, "note": "Unexpected, and perfect here."})
                    check("reorder / annotate list item", r.status_code == 200)
                    dup = await a.req("POST", f"/api/lists/{lid}/items", json={"book_id": books[picks[0]]["id"], "position": 9})
                    check("duplicate list item rejected", dup.status_code in (400, 409))
                if username == "sofia_lindqvist":
                    r = await a.req("DELETE", f"/api/lists/{lid}/items/{item_ids[-1]}")
                    check("remove list item", r.status_code in (200, 204))
                    other = await new_actors["amir_haddad"].req("PATCH", f"/api/lists/{lid}", json={"title": "hijack"})
                    check("cannot edit someone else's list (403)", other.status_code == 403)
            tl = await new_actors["dara_okafor"].req("POST", "/api/lists", json={"title": "Temp"})
            r = await new_actors["dara_okafor"].req("DELETE", f"/api/lists/{tl.json()['id']}")
            check("delete own list", r.status_code in (200, 204))
            check("lists created", len((await c.get("/api/lists?limit=50")).json()) >= 19)

            print("\n== Catalogue")
            r = await new_actors["amir_haddad"].req("POST", "/api/books", json={
                "title": "The Overstory", "author": "Richard Powers", "genre": "Literary Fiction", "year": 2018,
                "pages": 502, "description": "Nine strangers are drawn, each in their own way, to the defence of trees."})
            check("add a book", r.status_code == 201, r.text)
            if r.status_code == 201:
                bid = r.json()["id"]
                r = await new_actors["amir_haddad"].req("PATCH", f"/api/books/{bid}", json={"description": "Nine strangers are drawn into the defence of the oldest living things."})
                check("edit own book", r.status_code == 200)
                r = await new_actors["lucia_ferreira"].req("DELETE", f"/api/books/{bid}")
                check("cannot delete someone else's book (403)", r.status_code == 403)
                r = await new_actors["amir_haddad"].req("DELETE", f"/api/books/{bid}")
                check("delete own book", r.status_code in (200, 204))
            r = await c.get(f"/api/books/{books['Dune']['id']}/similar?limit=5")
            check("similar books (recommender)", r.status_code == 200 and len(r.json()) > 0)
            r = await c.get("/api/books/search-external", params={"q": "marginalia"})
            check("Open Library proxy answers", r.status_code in (200, 502), str(r.status_code))

            print("\n== Journal")
            drafts = {}
            for username, (title, sub, book, publish, body) in JOURNAL.items():
                a = new_actors[username]
                r = await a.req("POST", "/api/journal", json={
                    "title": title, "subtitle": sub, "body": body, "published": publish,
                    "book_id": books[book]["id"] if book in books else None})
                if r.status_code != 201:
                    check(f"{username} writes '{title}'", False, r.text)
                    continue
                if not publish:
                    drafts[username] = r.json()["id"]
            check("journal entries written", len((await c.get("/api/journal?limit=50")).json()) >= 8)
            did = drafts["callum_reyes"]
            r = await c.get(f"/api/journal/{did}")
            check("draft hidden from the public (404)", r.status_code == 404)
            r = await new_actors["amir_haddad"].req("GET", f"/api/journal/{did}")
            check("draft hidden from other readers (404)", r.status_code == 404)
            r = await new_actors["callum_reyes"].req("GET", f"/api/journal/{did}")
            check("author can read own draft", r.status_code == 200)
            mine = (await new_actors["sofia_lindqvist"].req("GET", "/api/journal/mine")).json()
            check("'my writing' lists drafts", any(not e["published"] for e in mine))
            r = await new_actors["callum_reyes"].req("PATCH", f"/api/journal/{did}", json={
                "published": True,
                "body": JOURNAL["callum_reyes"][4]
                + "\n\nIn *Mistborn* the map is a promise the plot has to keep: the Final Empire is wide, and every league of it costs."})
            check("publish a draft", r.status_code == 200 and r.json()["published_at"] is not None, r.text)
            a_entry = next(e for e in (await c.get("/api/journal?limit=50")).json() if e["author"]["username"] == "amir_haddad")
            r = await new_actors["lucia_ferreira"].req("PATCH", f"/api/journal/{a_entry['id']}", json={"title": "hijack"})
            check("cannot edit someone else's entry (403)", r.status_code == 403)
            tmp = await new_actors["dara_okafor"].req("POST", "/api/journal", json={"title": "Temp", "body": "x", "published": False})
            r = await new_actors["dara_okafor"].req("DELETE", f"/api/journal/{tmp.json()['id']}")
            check("delete own entry", r.status_code == 204)

            print("\n== Password reset")
            sent = {}

            async def fake_send(to, subject, text, html=None):
                sent["text"] = text

            import re
            import routers.users as users_router
            real = users_router.send_email
            users_router.send_email = fake_send
            try:
                r = await c.post("/api/users/forgot-password", json={"email": email_of("callum_reyes")})
                check("forgot-password accepted (202)", r.status_code == 202)
                r2 = await c.post("/api/users/forgot-password", json={"email": "nobody@example.com"})
                check("unknown email gets the same 202", r2.status_code == 202 and r2.json() == r.json())
                token = re.search(r"token=([\w-]+)", sent.get("text", ""))
                check("reset link emailed", bool(token))
                r = await c.post("/api/users/reset-password", json={"token": token.group(1), "password": "temporary-pass-1"})
                check("reset password", r.status_code == 200, r.text)
                r = await c.post("/api/users/reset-password", json={"token": token.group(1), "password": "another-pass-22"})
                check("reset link is single use", r.status_code == 400)
                await new_actors["callum_reyes"].login("temporary-pass-1")
                check("log in with the new password", bool(new_actors["callum_reyes"].headers))
                # restore the shared demo password through the same flow
                await c.post("/api/users/forgot-password", json={"email": email_of("callum_reyes")})
                token = re.search(r"token=([\w-]+)", sent["text"])
                r = await c.post("/api/users/reset-password", json={"token": token.group(1), "password": DEMO_PASSWORD})
                check("demo password restored", r.status_code == 200)
            finally:
                users_router.send_email = real

            print("\n== Backdating activity")
            now = datetime.now(UTC)
            async with SessionLocal() as db:
                for uid in new_ids:
                    logs = (await db.execute(select(models.ReadingLog).where(models.ReadingLog.user_id == uid))).scalars().all()
                    for l in logs:
                        l.created_at = now - timedelta(days=rng.randint(1, 25), hours=rng.randint(0, 20))
                await db.flush()
                lg = {l.id: aware(l.created_at) for l in (await db.execute(select(models.ReadingLog))).scalars()}
                for cm in (await db.execute(select(models.Comment))).scalars():
                    if cm.user_id in new_ids or lg.get(cm.log_id, now) > now - timedelta(days=26):
                        base = lg.get(cm.log_id, now - timedelta(days=2))
                        cm.created_at = min(now, base + timedelta(hours=rng.randint(1, 60)))
                for e in (await db.execute(select(models.JournalEntry).where(models.JournalEntry.user_id.in_(new_ids)))).scalars():
                    t = now - timedelta(days=rng.randint(1, 14), hours=rng.randint(0, 20))
                    e.created_at = t
                    e.updated_at = t
                    if e.published:
                        e.published_at = t
                await db.commit()
            print("  done")
        else:
            print("New readers already seeded — running read-only checks only.")

        print("\n== Read endpoints")
        some = existing_actors["mara_linden"]
        for name, url, hdr in [
            ("health", "/health", None), ("books", "/api/books", None), ("users", "/api/users", None),
            ("logs", "/api/logs?limit=5", None), ("popular reviews", "/api/logs?sort=popular&has_review=true&limit=5", None),
            ("lists", "/api/lists", None), ("journal", "/api/journal", None), ("groups", "/api/groups", None),
            ("feed", "/api/logs/feed", some.headers), ("friends popular", "/api/logs/friends/popular", some.headers),
            ("my journal", "/api/journal/mine", some.headers), ("me", "/api/users/me", some.headers),
        ]:
            r = await c.get(url, headers=hdr)
            check(f"GET {url.split('?')[0]}", r.status_code == 200, str(r.status_code))
        check("feed is protected (401)", (await c.get("/api/logs/feed")).status_code == 401)
        users = (await c.get("/api/users")).json()
        photo = [u for u in users if (u["avatar_url"] or "").startswith("https://randomuser.me")]
        check("readers have photo avatars", len(photo) >= len(EXISTING_PORTRAITS), str(len(photo)))

    failed = [n for n, ok, _ in REPORT if not ok]
    print(f"\n{len(REPORT) - len(failed)}/{len(REPORT)} checks passed" + (f"; FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
