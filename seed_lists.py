"""Seed themed reading lists across the existing reader accounts.

Books are matched by title against the catalogue (seed_books.py), so missing
titles are skipped rather than failing. Idempotent: a list is skipped if its
owner already has one with the same title.

    uv run python seed_lists.py
"""

import asyncio

from sqlalchemy import select

import models
from database import SessionLocal

# (owner username, title, description, ranked, [(book title, optional note)])
LISTS = [
    (
        "theo_baptiste",
        "Gothic Classics for Rainy Weekends",
        "Moors, manors and things that go bump in the night. Best read under a blanket with the window cracked open.",
        False,
        [
            ("Wuthering Heights", "Weather as a character."),
            ("Jane Eyre", None),
            ("Rebecca", "The housekeeper alone is worth the price of entry."),
            ("Dracula", None),
            ("Frankenstein", None),
            ("The Turn of the Screw", "Read it twice and pick a side."),
            ("The Haunting of Hill House", None),
        ],
    ),
    (
        "athenaeum_library",
        "The Science Fiction Canon",
        "Eight books that built the genre's vocabulary, in the order we'd hand them to a newcomer.",
        True,
        [
            ("Dune", None),
            ("Foundation", None),
            ("Neuromancer", None),
            ("The Left Hand of Darkness", "Where it stopped being about the gadgets."),
            ("Hyperion", None),
            ("Snow Crash", None),
            ("Solaris", None),
            ("The Dispossessed", None),
        ],
    ),
    (
        "priya_raman",
        "Cold Cases and Cosy Nights",
        "Mysteries that reward a second read, from the Golden Age to the grim and modern.",
        False,
        [
            ("And Then There Were None", None),
            ("The Murder of Roger Ackroyd", "The twist that started arguments in 1926."),
            ("The Hound of the Baskervilles", None),
            ("The Maltese Falcon", None),
            ("The Big Sleep", None),
            ("In the Woods", None),
        ],
    ),
    (
        "rowan_boyle",
        "Doorstoppers Worth the Wrist Strain",
        "Long books, ranked by how much I regret not starting them sooner.",
        True,
        [
            ("War and Peace", None),
            ("The Count of Monte Cristo", "Pure revenge-plot pleasure."),
            ("Les Miserables", None),
            ("Moby-Dick", None),
            ("The Brothers Karamazov", None),
            ("Anna Karenina", None),
            ("The Pillars of the Earth", None),
        ],
    ),
    (
        "mara_linden",
        "Poetry for People Who Think They Hate Poetry",
        "No homework. Read one poem aloud, out of order, and see what sticks.",
        False,
        [
            ("Ariel", None),
            ("Howl", None),
            ("Leaves of Grass", None),
            ("The Waste Land", None),
            ("Milk and Honey", None),
            ("Paradise Lost", "Start with Book I and the charm of Satan."),
        ],
    ),
    (
        "ines_marchetti",
        "Smart Nonfiction Without the Homework Feeling",
        "Big ideas, human voices.",
        False,
        [
            ("Sapiens", None),
            ("Thinking Fast and Slow", None),
            ("Educated", None),
            ("Born a Crime", None),
            ("Into the Wild", None),
            ("The Immortal Life of Henrietta Lacks", None),
            ("Silent Spring", None),
        ],
    ),
    (
        "felix_hartmann",
        "Fantasy Worlds I'd Move Into",
        "Ranked by how good the food probably is.",
        True,
        [
            ("The Hobbit", "Second breakfast. Enough said."),
            ("The Night Circus", None),
            ("The Name of the Wind", None),
            ("Piranesi", None),
            ("Mistborn", None),
            ("Uprooted", None),
            ("Jonathan Strange and Mr Norrell", None),
        ],
    ),
    (
        "tamsin_ellery",
        "Quiet Books, Long Echoes",
        "Nothing explodes. Everything lingers.",
        False,
        [
            ("Klara and the Sun", None),
            ("Never Let Me Go", None),
            ("The Remains of the Day", "A masterclass in what a narrator won't say."),
            ("Norwegian Wood", None),
            ("The Bell Jar", None),
            ("Giovanni's Room", None),
        ],
    ),
    (
        "elin_oseberg",
        "The Greeks, Retold",
        "Old stories, new mouths: the myths as told by writers who gave the women and the minor characters a voice.",
        False,
        [
            ("The Odyssey", "Start here, then read the others against it."),
            ("Circe", None),
            ("The Song of Achilles", None),
            ("Meditations", None),
        ],
    ),
]


async def main() -> None:
    async with SessionLocal() as db:
        users = {u.username: u for u in (await db.execute(select(models.User))).scalars()}
        books = {b.title: b for b in (await db.execute(select(models.Book))).scalars()}
        made = 0
        for owner, title, desc, ranked, picks in LISTS:
            user = users.get(owner)
            if user is None:
                print(f"skip '{title}': no user {owner}")
                continue
            exists = (
                await db.execute(
                    select(models.ReadingList).where(
                        models.ReadingList.user_id == user.id,
                        models.ReadingList.title == title,
                    )
                )
            ).scalars().first()
            if exists:
                continue
            lst = models.ReadingList(user_id=user.id, title=title, description=desc, is_ranked=ranked)
            db.add(lst)
            await db.flush()
            pos = 1
            for book_title, note in picks:
                book = books.get(book_title)
                if book is None:
                    print(f"  missing book: {book_title}")
                    continue
                db.add(models.ListItem(list_id=lst.id, book_id=book.id, position=pos, note=note))
                pos += 1
            made += 1
        await db.commit()
        print(f"Seeded {made} lists.")


if __name__ == "__main__":
    asyncio.run(main())
