"""Seed the Journal with example essays from several reader accounts.

Each exercises different markdown features (tables, task lists, footnotes,
code, images, nested lists). Idempotent: skips an entry whose author already
has one with the same title. Run after `alembic upgrade head`:

    uv run python seed_journal.py
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

import models
from database import SessionLocal

TITLE = "In Praise of the Margin"
SUBTITLE = "What a medieval monastery, a snail and a name on a rose can teach us about reading with a pencil."
BOOK_TITLE = "The Name of the Rose"

BODY = """\
There is a drawing in the margin of a thirteenth-century manuscript of a knight, lance levelled, charging a snail. The snail is winning. Nobody knows who drew it or why, only that a scribe, somewhere in the middle of copying out something solemn, looked at the empty space beside the text and decided it needed a joke.

That is the oldest argument for the margin: it is where the reader is allowed to be a person.

## The page is a conversation

We tend to picture a book as a finished thing, a sealed statement handed down from the author. The margin quietly disagrees. It is the one part of the page the author left blank, and every reader who has ever picked up a pencil has understood it as an *invitation*.

Look at what people do with it:

- They argue. *"No — surely the opposite."*
- They remember. *"Read this on the train, the week everything changed."*
- They simply react: a line down the side, a star, a question mark, a single furious **NO**.
- They write to the next reader, knowing there will be one.

Pierre de Fermat, so the story goes, scribbled in his copy of an ancient arithmetic text that he had found a remarkable proof but that the margin was too small to hold it. Mathematicians spent more than three centuries chasing the ghost of that sentence. A margin note outlived its author's silence and bent the course of a field.

> A book you have never written in is a book you have only half read.

## Umberto Eco's library of locked doors

No novel understands the stakes of the written page better than *The Name of the Rose*. Its monastery library is a labyrinth, guarded and gated, because the people who run it believe that what a book *says* matters less than who is permitted to read it, and what they might do next.

The detective, William of Baskerville, is the kind of reader the labyrinth fears: one who pulls on a thread. Meanwhile the monks in the scriptorium below are busily doing what monks did, copying sacred texts while the borders of their pages fill with beasts, jesters and impossible creatures. Eco knows the joke is the point. The solemn centre of the page and the unruly edge exist together, and the edge is where you learn what the copyists were actually thinking.

The book is, among other things, about the fear of laughter, and a library that would rather burn than let the margin speak.

## How to write in a book

If you have been taught that writing in books is vandalism, here is a gentle case for relapse. You do not need a system. A few habits are plenty:

1. **Underline sparingly.** If everything is underlined, nothing is.
2. **Ask a question** wherever you feel resistance. Resistance is where the book is doing its work.
3. **Write the date** on a note that matters. You will want to meet that version of yourself again.
4. **Disagree in full sentences.** Arguments written down are the ones you keep.

Use a pencil if the permanence frightens you. The point is not neat handwriting. The point is to leave a trace of your attention.

## Marginalia, but for everyone

This is, in the end, why a place like Athenaeum exists: a shared margin. A reading log is a note in the corner of a book, *I was here, this is what it did to me*, and a journal entry is the same instinct given room to breathe. Somebody will open the same book next year, and find what you left.

So write in the margin. Draw the snail. Win the fight.

---

*What is the best note you have ever found in a borrowed book? Write it up in your own journal entry, and link the book it came from.*
"""

GOTHIC = """\
Every great gothic novel has a *climate* before it has a plot. Before anyone is murdered, haunted or disinherited, the weather has already told you how this is going to end.

## A field guide

| Book | Weather | What it's really saying |
| --- | --- | --- |
| *Wuthering Heights* | Wind, sleet, a moor with opinions | Nature doesn't care about your feelings |
| *Rebecca* | Sea fog, then fire | The past is never done with the house |
| *Jane Eyre* | Rain at the right moments | Feeling and fate arrive together |
| *The Haunting of Hill House* | Still, bright, wrong | Something is off *indoors* |

## Three rules of gothic weather

1. **Weather arrives before consequence.** The storm is the narrator clearing its throat.
2. **Interiors are weather too.**
   - A cold room is a verdict.
   - A fire lit for you is a promise, or a trap.
   - A locked wing is a forecast.
3. **Clear skies are the scariest.** When the sun comes out in *Hill House*, the book has stopped pretending.

## A reading checklist

- [x] Read it with the window open
- [x] Underline every mention of the weather
- [ ] Notice the first sentence where the sky and a person disagree
- [ ] Read the ending a second time, in daylight

> I am no bird; and no net ensnares me.

That line from *Jane Eyre* is only slightly about a bird.[^1]

---

[^1]: The point is that Brontë lets the landscape do the arguing the characters can't.
"""

DUNE = """\
*Dune* is usually sold as a desert adventure. Read it again with a field notebook and it turns out to be something stranger: a book about **ecology as destiny**.

# The planet is the protagonist

Arrakis is not a backdrop. Water is currency, religion and politics; the spice is the reason anyone cares, and the worms are the reason anyone survives. Almost every plot beat is an *ecological fact in disguise*.

## What the book gets right

- Resources shape power: whoever controls the scarce thing controls the rest
  - water discipline in the sietch
  - spice as an economy and a drug
- Long-term thinking beats short-term strength
- ~~Heroes save worlds~~ **Ecosystems outlast heroes**

## The question to ask every chapter

```text
Who benefits from this resource being scarce?
```

Keep that on a sticky note. It makes every scene in the book sharper.

## Reading plan

- [x] Part One: Dune
- [x] Part Two: Muad'Dib
- [ ] Part Three: The Prophet
- [ ] Appendix: **The Ecology of Dune** (don't skip it)

Visit the book's page in the catalogue, then come back and tell us which scene made you look at your own tap water differently.
"""

ANNOTATE = """\
Most advice about marking up books is either too precious ("use seven colours") or too vague ("just write what you think"). Here is a method that has survived years of train commutes.

![Fahrenheit 451](__COVER_F451__)

*The best book to practise on is one that's already about books.*

## The five marks

| Mark | Meaning | Use it when |
| :--- | :---: | ---: |
| `\\|` in the margin | Strong line | You'd quote it |
| `?` | I don't believe this | You'd argue |
| `!` | Surprise | The author earned it |
| `→` | Connects to another page | You noticed a pattern |
| `§` | Come back to this | Not now, later |

## The routine

1. Read the page **without** the pencil.
2. Go back and mark only what survived your memory.
3. At the end of the chapter, write one sentence at the top of the page:
   - what happened
   - what it did to you
4. Once a week, flip through *only* the marks.

## A tiny script, if you want to keep digital notes

```python
from datetime import date

def note(book: str, page: int, mark: str, text: str) -> str:
    return f"{date.today()} | {book} p.{page} [{mark}] {text}"

print(note("Fahrenheit 451", 12, "!", "Books as the thing worth burning"))
```

## Pocket rules

- [x] Pencil, not pen
- [x] Date the notes that matter
- [ ] Never explain what the text already says
- [ ] Disagree in *full sentences*

> Margin notes are letters to a future reader. Be someone they'd be glad to meet.

More at <https://en.wikipedia.org/wiki/Marginalia>.
"""

NARRATOR = """\
Kazuo Ishiguro's *The Remains of the Day* is narrated by a man who is, by every measure he'd accept, an excellent butler. It is also one of the great studies of what a narrator **won't** say.

## What Stevens tells us

1. He served at Darlington Hall for decades.
2. He believes in *dignity*, which he defines carefully and often.
3. He takes a road trip.
   1. The trip is a pretext.
   2. The destination is a person.
   3. The real journey is back through memory.

## What Stevens doesn't tell us

- How he felt in the corridor outside the door
- What he really thought of his employer's politics
- Why the answer to a simple question takes four pages[^dignity]

## How to read the gaps

| Technique | Example | Effect |
| --- | --- | --- |
| Deflection | Changes the subject to protocol | We learn what hurts |
| Over-explaining | Defends a choice no one questioned | We learn what he fears |
| Silence | A scene ends mid-feeling | We supply the feeling |

## A reader's checklist

- [x] Notice the first time he says *dignity*
- [x] Mark each place the subject changes abruptly
- [ ] Ask who he is *performing* for
- [ ] Reread the last chapter slowly

The lesson is not that Stevens lies. It is that a narrator can be entirely sincere and still leave the most important thing out.

[^dignity]: Stevens would call this "being thorough".
"""

POSTS = [
    # (author username, title, subtitle, body, book title, days ago)
    ("athenaeum_library", TITLE, SUBTITLE, BODY, BOOK_TITLE, 6),
    (
        "theo_baptiste",
        "A Field Guide to Gothic Weather",
        "In a gothic novel the climate arrives before the plot. A short guide to reading the sky.",
        GOTHIC,
        "Wuthering Heights",
        4,
    ),
    (
        "jonah_whitfield",
        "Reading Dune as an Ecologist",
        "Strip away the prophecy and the desert adventure turns into a book about resources, patience and power.",
        DUNE,
        "Dune",
        3,
    ),
    (
        "mara_linden",
        "How to Annotate a Book (a Practical Method)",
        "Five marks, one routine, and no coloured highlighters.",
        ANNOTATE,
        "Fahrenheit 451",
        2,
    ),
    (
        "tamsin_ellery",
        "What the Butler Doesn't Say",
        "Ishiguro's Stevens is a lesson in how much a narrator can leave out while telling the truth.",
        NARRATOR,
        "The Remains of the Day",
        1,
    ),
]


async def main() -> None:
    async with SessionLocal() as db:
        users = {u.username: u for u in (await db.execute(select(models.User))).scalars()}
        books = {b.title: b for b in (await db.execute(select(models.Book))).scalars()}
        f451 = books.get("Fahrenheit 451")
        made = 0
        for username, title, subtitle, body, book_title, days_ago in POSTS:
            author = users.get(username)
            if author is None:
                print(f"skip '{title}': no user {username}")
                continue
            exists = (
                await db.execute(
                    select(models.JournalEntry).where(
                        models.JournalEntry.user_id == author.id,
                        models.JournalEntry.title == title,
                    )
                )
            ).scalars().first()
            if exists:
                continue
            book = books.get(book_title)
            when = datetime.now(UTC) - timedelta(days=days_ago)
            db.add(
                models.JournalEntry(
                    user_id=author.id,
                    book_id=book.id if book else None,
                    title=title,
                    subtitle=subtitle,
                    body=body.replace("__COVER_F451__", (f451.cover_url if f451 and f451.cover_url else "")),
                    published=True,
                    created_at=when,
                    published_at=when,
                )
            )
            made += 1
        await db.commit()
        print(f"Seeded {made} journal entries.")


if __name__ == "__main__":
    asyncio.run(main())
