"""Seed the catalogue with a broad, real spread of books via Open Library.

Reuses the exact same fetch this app already exposes at
GET /api/books/search-external — this script just drives it across a
curated list of titles instead of one search box at a time, then writes
the results with the existing Book model directly (no HTTP round trip to
our own API needed since this runs server-side already).

All seeded books are owned by a dedicated "Athenaeum Library" account, not
a real user — keeps them clearly distinguishable from anything a real
tester adds. Safe to re-run: skips any (title, author) pair already in the
catalogue, so running this again after adding your own books just fills in
whatever's still missing.

    uv run python seed_books.py
"""

import asyncio
import secrets

import httpx
from sqlalchemy import func, select

import models
from auth import hash_password
from database import SessionLocal

LIBRARY_USERNAME = "athenaeum_library"
LIBRARY_EMAIL = "library@athenaeum.app"

# (title, author, genre) — real, well-known books, not generated. Genre
# strings are kept consistent within each group since Discover derives its
# filter chips straight from whatever's in the data.
BOOKS = [
    # Literary Fiction
    ("To Kill a Mockingbird", "Harper Lee", "Literary Fiction"),
    ("Beloved", "Toni Morrison", "Literary Fiction"),
    ("Mrs Dalloway", "Virginia Woolf", "Literary Fiction"),
    ("The Great Gatsby", "F. Scott Fitzgerald", "Literary Fiction"),
    ("One Hundred Years of Solitude", "Gabriel Garcia Marquez", "Literary Fiction"),
    ("The Catcher in the Rye", "J.D. Salinger", "Literary Fiction"),
    ("Middlemarch", "George Eliot", "Literary Fiction"),
    ("Norwegian Wood", "Haruki Murakami", "Literary Fiction"),
    ("The Remains of the Day", "Kazuo Ishiguro", "Literary Fiction"),
    ("White Teeth", "Zadie Smith", "Literary Fiction"),
    ("Never Let Me Go", "Kazuo Ishiguro", "Literary Fiction"),
    ("The Bell Jar", "Sylvia Plath", "Literary Fiction"),
    ("A Little Life", "Hanya Yanagihara", "Literary Fiction"),
    ("The Goldfinch", "Donna Tartt", "Literary Fiction"),
    ("Middlesex", "Jeffrey Eugenides", "Literary Fiction"),
    ("Atonement", "Ian McEwan", "Literary Fiction"),
    ("The Corrections", "Jonathan Franzen", "Literary Fiction"),
    ("Wide Sargasso Sea", "Jean Rhys", "Literary Fiction"),
    ("Giovanni's Room", "James Baldwin", "Literary Fiction"),
    ("Beloved Country", "Alan Paton", "Literary Fiction"),

    # Science Fiction
    ("Dune", "Frank Herbert", "Science Fiction"),
    ("Foundation", "Isaac Asimov", "Science Fiction"),
    ("Neuromancer", "William Gibson", "Science Fiction"),
    ("The Left Hand of Darkness", "Ursula K. Le Guin", "Science Fiction"),
    ("Snow Crash", "Neal Stephenson", "Science Fiction"),
    ("Ender's Game", "Orson Scott Card", "Science Fiction"),
    ("The Dispossessed", "Ursula K. Le Guin", "Science Fiction"),
    ("Hyperion", "Dan Simmons", "Science Fiction"),
    ("The Martian", "Andy Weir", "Science Fiction"),
    ("Fahrenheit 451", "Ray Bradbury", "Science Fiction"),
    ("Brave New World", "Aldous Huxley", "Science Fiction"),
    ("Nineteen Eighty-Four", "George Orwell", "Science Fiction"),
    ("Slaughterhouse-Five", "Kurt Vonnegut", "Science Fiction"),
    ("The Three-Body Problem", "Liu Cixin", "Science Fiction"),
    ("Children of Time", "Adrian Tchaikovsky", "Science Fiction"),
    ("A Fire Upon the Deep", "Vernor Vinge", "Science Fiction"),
    ("Ancillary Justice", "Ann Leckie", "Science Fiction"),
    ("The Forever War", "Joe Haldeman", "Science Fiction"),
    ("Solaris", "Stanislaw Lem", "Science Fiction"),
    ("Do Androids Dream of Electric Sheep", "Philip K. Dick", "Science Fiction"),

    # Fantasy
    ("The Hobbit", "J.R.R. Tolkien", "Fantasy"),
    ("The Fellowship of the Ring", "J.R.R. Tolkien", "Fantasy"),
    ("A Game of Thrones", "George R.R. Martin", "Fantasy"),
    ("The Name of the Wind", "Patrick Rothfuss", "Fantasy"),
    ("The Way of Kings", "Brandon Sanderson", "Fantasy"),
    ("Mistborn", "Brandon Sanderson", "Fantasy"),
    ("American Gods", "Neil Gaiman", "Fantasy"),
    ("Good Omens", "Terry Pratchett", "Fantasy"),
    ("The Color of Magic", "Terry Pratchett", "Fantasy"),
    ("Jonathan Strange and Mr Norrell", "Susanna Clarke", "Fantasy"),
    ("The Lies of Locke Lamora", "Scott Lynch", "Fantasy"),
    ("The Priory of the Orange Tree", "Samantha Shannon", "Fantasy"),
    ("Circe", "Madeline Miller", "Fantasy"),
    ("The Song of Achilles", "Madeline Miller", "Fantasy"),
    ("Piranesi", "Susanna Clarke", "Fantasy"),
    ("The Night Circus", "Erin Morgenstern", "Fantasy"),
    ("Uprooted", "Naomi Novik", "Fantasy"),
    ("The Golden Compass", "Philip Pullman", "Fantasy"),
    ("Wizard's First Rule", "Terry Goodkind", "Fantasy"),
    ("The Blade Itself", "Joe Abercrombie", "Fantasy"),

    # Mystery
    ("Gone Girl", "Gillian Flynn", "Mystery"),
    ("The Girl with the Dragon Tattoo", "Stieg Larsson", "Mystery"),
    ("And Then There Were None", "Agatha Christie", "Mystery"),
    ("The Silent Patient", "Alex Michaelides", "Mystery"),
    ("The Big Sleep", "Raymond Chandler", "Mystery"),
    ("In the Woods", "Tana French", "Mystery"),
    ("The Da Vinci Code", "Dan Brown", "Mystery"),
    ("Rebecca", "Daphne du Maurier", "Mystery"),
    ("The Talented Mr Ripley", "Patricia Highsmith", "Mystery"),
    ("Sharp Objects", "Gillian Flynn", "Mystery"),
    ("The Murder of Roger Ackroyd", "Agatha Christie", "Mystery"),
    ("Presumed Innocent", "Scott Turow", "Mystery"),
    ("The Girl on the Train", "Paula Hawkins", "Mystery"),
    ("Mystic River", "Dennis Lehane", "Mystery"),
    ("The Hound of the Baskervilles", "Arthur Conan Doyle", "Mystery"),
    ("The Name of the Rose", "Umberto Eco", "Mystery"),
    ("Killing Floor", "Lee Child", "Mystery"),
    ("The Postman Always Rings Twice", "James M. Cain", "Mystery"),
    ("A Study in Scarlet", "Arthur Conan Doyle", "Mystery"),
    ("The Maltese Falcon", "Dashiell Hammett", "Mystery"),

    # Classic Literature
    ("Pride and Prejudice", "Jane Austen", "Classic Literature"),
    ("Moby-Dick", "Herman Melville", "Classic Literature"),
    ("War and Peace", "Leo Tolstoy", "Classic Literature"),
    ("Crime and Punishment", "Fyodor Dostoevsky", "Classic Literature"),
    ("Jane Eyre", "Charlotte Bronte", "Classic Literature"),
    ("Wuthering Heights", "Emily Bronte", "Classic Literature"),
    ("Anna Karenina", "Leo Tolstoy", "Classic Literature"),
    ("The Brothers Karamazov", "Fyodor Dostoevsky", "Classic Literature"),
    ("Great Expectations", "Charles Dickens", "Classic Literature"),
    ("Don Quixote", "Miguel de Cervantes", "Classic Literature"),
    ("The Odyssey", "Homer", "Classic Literature"),
    ("Frankenstein", "Mary Shelley", "Classic Literature"),
    ("Dracula", "Bram Stoker", "Classic Literature"),
    ("The Picture of Dorian Gray", "Oscar Wilde", "Classic Literature"),
    ("Madame Bovary", "Gustave Flaubert", "Classic Literature"),
    ("The Count of Monte Cristo", "Alexandre Dumas", "Classic Literature"),
    ("Les Miserables", "Victor Hugo", "Classic Literature"),
    ("A Tale of Two Cities", "Charles Dickens", "Classic Literature"),
    ("The Scarlet Letter", "Nathaniel Hawthorne", "Classic Literature"),
    ("Heart of Darkness", "Joseph Conrad", "Classic Literature"),

    # Horror
    ("The Shining", "Stephen King", "Horror"),
    ("It", "Stephen King", "Horror"),
    ("House of Leaves", "Mark Z. Danielewski", "Horror"),
    ("The Haunting of Hill House", "Shirley Jackson", "Horror"),
    ("Something Wicked This Way Comes", "Ray Bradbury", "Horror"),
    ("Mexican Gothic", "Silvia Moreno-Garcia", "Horror"),
    ("The Exorcist", "William Peter Blatty", "Horror"),
    ("Interview with the Vampire", "Anne Rice", "Horror"),
    ("Pet Sematary", "Stephen King", "Horror"),
    ("The Turn of the Screw", "Henry James", "Horror"),
    ("Rosemary's Baby", "Ira Levin", "Horror"),
    ("Bird Box", "Josh Malerman", "Horror"),
    ("The Fisherman", "John Langan", "Horror"),
    ("Hell House", "Richard Matheson", "Horror"),

    # Romance
    ("Outlander", "Diana Gabaldon", "Romance"),
    ("The Notebook", "Nicholas Sparks", "Romance"),
    ("Me Before You", "Jojo Moyes", "Romance"),
    ("Beach Read", "Emily Henry", "Romance"),
    ("The Hating Game", "Sally Thorne", "Romance"),
    ("Red White and Royal Blue", "Casey McQuiston", "Romance"),
    ("It Ends with Us", "Colleen Hoover", "Romance"),
    ("Twilight", "Stephenie Meyer", "Romance"),
    ("The Time Traveler's Wife", "Audrey Niffenegger", "Romance"),
    ("Eleanor and Park", "Rainbow Rowell", "Romance"),
    ("Persuasion", "Jane Austen", "Romance"),
    ("Normal People", "Sally Rooney", "Romance"),
    ("One Day", "David Nicholls", "Romance"),
    ("Love in the Time of Cholera", "Gabriel Garcia Marquez", "Romance"),

    # Young Adult
    ("The Hunger Games", "Suzanne Collins", "Young Adult"),
    ("Divergent", "Veronica Roth", "Young Adult"),
    ("The Perks of Being a Wallflower", "Stephen Chbosky", "Young Adult"),
    ("Speak", "Laurie Halse Anderson", "Young Adult"),
    ("Thirteen Reasons Why", "Jay Asher", "Young Adult"),
    ("The Book Thief", "Markus Zusak", "Young Adult"),
    ("Percy Jackson and the Lightning Thief", "Rick Riordan", "Young Adult"),
    ("Six of Crows", "Leigh Bardugo", "Young Adult"),
    ("The Fault in Our Stars", "John Green", "Young Adult"),
    ("Looking for Alaska", "John Green", "Young Adult"),
    ("Paper Towns", "John Green", "Young Adult"),
    ("Wonder", "R.J. Palacio", "Young Adult"),
    ("Holes", "Louis Sachar", "Young Adult"),
    ("The Giver", "Lois Lowry", "Young Adult"),
    ("Legend", "Marie Lu", "Young Adult"),
    ("An Ember in the Ashes", "Sabaa Tahir", "Young Adult"),

    # Nonfiction
    ("Sapiens", "Yuval Noah Harari", "Nonfiction"),
    ("Educated", "Tara Westover", "Nonfiction"),
    ("Into the Wild", "Jon Krakauer", "Nonfiction"),
    ("The Immortal Life of Henrietta Lacks", "Rebecca Skloot", "Nonfiction"),
    ("A Brief History of Time", "Stephen Hawking", "Nonfiction"),
    ("Thinking Fast and Slow", "Daniel Kahneman", "Nonfiction"),
    ("Man's Search for Meaning", "Viktor Frankl", "Nonfiction"),
    ("Silent Spring", "Rachel Carson", "Nonfiction"),
    ("The Diary of a Young Girl", "Anne Frank", "Nonfiction"),
    ("In Cold Blood", "Truman Capote", "Nonfiction"),
    ("Born a Crime", "Trevor Noah", "Nonfiction"),
    ("Bad Blood", "John Carreyrou", "Nonfiction"),
    ("Just Mercy", "Bryan Stevenson", "Nonfiction"),
    ("The Warmth of Other Suns", "Isabel Wilkerson", "Nonfiction"),
    ("Guns Germs and Steel", "Jared Diamond", "Nonfiction"),

    # Poetry
    ("Leaves of Grass", "Walt Whitman", "Poetry"),
    ("The Waste Land", "T.S. Eliot", "Poetry"),
    ("Ariel", "Sylvia Plath", "Poetry"),
    ("Milk and Honey", "Rupi Kaur", "Poetry"),
    ("Howl", "Allen Ginsberg", "Poetry"),
    ("The Sun and Her Flowers", "Rupi Kaur", "Poetry"),
    ("Paradise Lost", "John Milton", "Poetry"),
    ("The Canterbury Tales", "Geoffrey Chaucer", "Poetry"),

    # Historical Fiction
    ("All the Light We Cannot See", "Anthony Doerr", "Historical Fiction"),
    ("The Nightingale", "Kristin Hannah", "Historical Fiction"),
    ("Pachinko", "Min Jin Lee", "Historical Fiction"),
    ("The Pillars of the Earth", "Ken Follett", "Historical Fiction"),
    ("Wolf Hall", "Hilary Mantel", "Historical Fiction"),
    ("The Other Boleyn Girl", "Philippa Gregory", "Historical Fiction"),
    ("Cutting for Stone", "Abraham Verghese", "Historical Fiction"),
    ("The Kite Runner", "Khaled Hosseini", "Historical Fiction"),
    ("A Thousand Splendid Suns", "Khaled Hosseini", "Historical Fiction"),
    ("The Tattooist of Auschwitz", "Heather Morris", "Historical Fiction"),
    ("Homegoing", "Yaa Gyasi", "Historical Fiction"),
    ("East of Eden", "John Steinbeck", "Historical Fiction"),
    ("The Grapes of Wrath", "John Steinbeck", "Historical Fiction"),
    ("Cold Mountain", "Charles Frazier", "Historical Fiction"),

    # Contemporary Fiction
    ("Where the Crawdads Sing", "Delia Owens", "Contemporary Fiction"),
    ("Little Fires Everywhere", "Celeste Ng", "Contemporary Fiction"),
    ("The Seven Husbands of Evelyn Hugo", "Taylor Jenkins Reid", "Contemporary Fiction"),
    ("Conversations with Friends", "Sally Rooney", "Contemporary Fiction"),
    ("Klara and the Sun", "Kazuo Ishiguro", "Contemporary Fiction"),
    ("The Midnight Library", "Matt Haig", "Contemporary Fiction"),
    ("Lessons in Chemistry", "Bonnie Garmus", "Contemporary Fiction"),
    ("Tomorrow and Tomorrow and Tomorrow", "Gabrielle Zevin", "Contemporary Fiction"),
    ("Demon Copperhead", "Barbara Kingsolver", "Contemporary Fiction"),
    ("The Vanishing Half", "Brit Bennett", "Contemporary Fiction"),
    ("Hamnet", "Maggie O'Farrell", "Contemporary Fiction"),
    ("Exit West", "Mohsin Hamid", "Contemporary Fiction"),
    ("A Man Called Ove", "Fredrik Backman", "Contemporary Fiction"),
    ("The House in the Cerulean Sea", "TJ Klune", "Contemporary Fiction"),
]


async def get_or_create_library_user(db) -> models.User:
    result = await db.execute(
        select(models.User).where(func.lower(models.User.username) == LIBRARY_USERNAME),
    )
    user = result.scalars().first()
    if user:
        return user

    user = models.User(
        username=LIBRARY_USERNAME,
        email=LIBRARY_EMAIL,
        password_hash=hash_password(secrets.token_urlsafe(32)),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    print(f"created system account @{LIBRARY_USERNAME} (id={user.id})")
    return user


async def fetch_metadata(client: httpx.AsyncClient, title: str, author: str) -> dict:
    response = await client.get(
        "https://openlibrary.org/search.json",
        params={"q": f"{title} {author}", "limit": 1},
        timeout=10,
    )
    response.raise_for_status()
    docs = response.json().get("docs", [])
    if not docs:
        return {}

    doc = docs[0]
    cover_id = doc.get("cover_i")
    meta = {
        "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None,
        "year": doc.get("first_publish_year"),
        "pages": doc.get("number_of_pages_median"),
        "description": None,
    }

    work_key = doc.get("key")  # e.g. "/works/OL27448W"
    if work_key:
        try:
            work_response = await client.get(f"https://openlibrary.org{work_key}.json", timeout=10)
            work_response.raise_for_status()
            raw = work_response.json().get("description")
            if isinstance(raw, dict):
                raw = raw.get("value")
            if isinstance(raw, str) and raw.strip():
                meta["description"] = raw.strip()[:1000]
        except httpx.HTTPError:
            pass

    return meta


async def seed():
    async with SessionLocal() as db:
        library_user = await get_or_create_library_user(db)

        result = await db.execute(select(models.Book.title, models.Book.author))
        existing = {(t.lower(), a.lower()) for t, a in result.all()}

        created, skipped, failed = 0, 0, 0

        async with httpx.AsyncClient() as client:
            for title, author, genre in BOOKS:
                if (title.lower(), author.lower()) in existing:
                    skipped += 1
                    continue

                try:
                    meta = await fetch_metadata(client, title, author)
                except httpx.HTTPError as err:
                    print(f"  ! {title} — Open Library fetch failed: {err}")
                    failed += 1
                    continue

                new_book = models.Book(
                    title=title,
                    author=author,
                    genre=genre,
                    year=meta.get("year") or 2000,
                    cover_url=meta.get("cover_url"),
                    pages=meta.get("pages") or 300,
                    description=meta.get("description")
                    or f"A {genre.lower()} title by {author}, catalogued for readers to log and review.",
                    user_id=library_user.id,
                    owner=library_user,
                )
                db.add(new_book)
                await db.commit()
                created += 1
                print(f"  + {title} ({author})")

                await asyncio.sleep(0.15)  # stay polite to Open Library

        print(f"\ndone: {created} added, {skipped} already present, {failed} failed")


if __name__ == "__main__":
    asyncio.run(seed())
