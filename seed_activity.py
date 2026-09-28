"""Seed reader activity on top of the seeded catalogue.

seed_books.py fills the shelves with real books owned by a system account, but
the app around them is empty — no readers, no logs, no comments, no lists, no
groups. This script adds that layer: ten fake readers, who follows whom, a few
hundred reading logs with real reviews, comment threads, likes, reading lists
and two book clubs, so every page has something in it when you click around.

Like seed_books.py this writes straight to the database through SessionLocal
and the SQLAlchemy models rather than calling our own HTTP API, and it is safe
to re-run: every entity is matched on a natural key first, so a second run
reports "skipped" instead of piling up duplicates.

Dedupe keys:
  User         username
  Follow       (follower_id, followed_id)
  ReadingLog   (user_id, book_id)         one reading-through per reader per book
  Comment      (log_id, body)
  Like         (user_id, log_id)          also a real unique constraint
  ReadingList  (user_id, title)
  ListItem     (list_id, book_id)         also a real unique constraint
  Group        (owner_id, name)
  GroupMember  (group_id, user_id)        also a real unique constraint
  Post         (group_id, body)

Chat and audio are deliberately left alone — models.Message and
models.AudioSession are tested live by opening two browser sessions.

    uv run python seed_activity.py

Sign in as any of the seeded readers with the password below if you want to
see the Feed and your own profile as a populated account:

    username: mara_linden   (or the other nine, see READERS below)
    password: vellum-2024
"""

import asyncio
import random
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select

import models
from auth import hash_password
from database import SessionLocal

# Every seeded reader shares this password so you can actually log in and look
# around. Hashing still goes through hash_password() like any real signup, so
# no plaintext ever lands in the table.
DEMO_PASSWORD = "vellum-2024"

# (username, email, display-ish handle) — written like people, not "user1".
READERS = [
    ("mara_linden", "mara.linden@athenaeum.app"),
    ("theo_baptiste", "theo.baptiste@athenaeum.app"),
    ("priya_raman", "priya.raman@athenaeum.app"),
    ("elin_oseberg", "elin.oseberg@athenaeum.app"),
    ("jonah_whitfield", "jonah.whitfield@athenaeum.app"),
    ("naomi_okonkwo", "naomi.okonkwo@athenaeum.app"),
    ("felix_hartmann", "felix.hartmann@athenaeum.app"),
    ("ines_marchetti", "ines.marchetti@athenaeum.app"),
    ("rowan_boyle", "rowan.boyle@athenaeum.app"),
    ("tamsin_ellery", "tamsin.ellery@athenaeum.app"),
]

# Who follows whom, by username. Hand-written so the follow graph looks like a
# real one: a few mutual pairs, some one-sided crushes on a writer's shelf.
# Anyone not listed as a follower of someone still gets a random 2-4 follows
# added on top, so nobody ends up with an empty feed.
FOLLOW_EDGES = [
    ("mara_linden", "theo_baptiste"),
    ("mara_linden", "tamsin_ellery"),
    ("mara_linden", "jonah_whitfield"),
    ("theo_baptiste", "mara_linden"),
    ("theo_baptiste", "priya_raman"),
    ("theo_baptiste", "rowan_boyle"),
    ("priya_raman", "naomi_okonkwo"),
    ("priya_raman", "ines_marchetti"),
    ("priya_raman", "mara_linden"),
    ("elin_oseberg", "felix_hartmann"),
    ("elin_oseberg", "tamsin_ellery"),
    ("jonah_whitfield", "mara_linden"),
    ("jonah_whitfield", "rowan_boyle"),
    ("jonah_whitfield", "felix_hartmann"),
    ("naomi_okonkwo", "priya_raman"),
    ("naomi_okonkwo", "elin_oseberg"),
    ("felix_hartmann", "elin_oseberg"),
    ("felix_hartmann", "naomi_okonkwo"),
    ("ines_marchetti", "tamsin_ellery"),
    ("ines_marchetti", "priya_raman"),
    ("rowan_boyle", "jonah_whitfield"),
    ("rowan_boyle", "felix_hartmann"),
    ("tamsin_ellery", "mara_linden"),
    ("tamsin_ellery", "ines_marchetti"),
]

# Which books get reading logs, per genre. Chosen to cover every genre in the
# catalogue with a few titles each rather than the first N alphabetically, so
# clicking through any genre filter in Discover lands on real activity.
LOGGED_BOOKS = {
    "Literary Fiction": [
        "To Kill a Mockingbird", "Beloved", "Mrs Dalloway", "The Great Gatsby",
        "One Hundred Years of Solitude", "The Catcher in the Rye", "Middlemarch",
        "Norwegian Wood", "The Remains of the Day", "The Bell Jar", "Atonement",
        "Wide Sargasso Sea",
    ],
    "Science Fiction": [
        "Dune", "Neuromancer", "The Left Hand of Darkness", "Snow Crash",
        "The Dispossessed", "Hyperion", "The Martian", "Fahrenheit 451",
        "Brave New World", "Slaughterhouse-Five", "The Three-Body Problem",
        "Children of Time", "A Fire Upon the Deep", "Ancillary Justice", "Solaris",
    ],
    "Fantasy": [
        "The Hobbit", "A Game of Thrones", "The Name of the Wind", "The Way of Kings",
        "American Gods", "Good Omens", "Piranesi", "The Song of Achilles",
        "Jonathan Strange and Mr Norrell", "Uprooted", "The Night Circus",
    ],
    "Mystery": [
        "Gone Girl", "The Girl with the Dragon Tattoo", "And Then There Were None",
        "The Silent Patient", "The Big Sleep", "In the Woods", "Rebecca",
        "The Talented Mr Ripley", "Sharp Objects", "The Name of the Rose",
        "The Postman Always Rings Twice",
    ],
    "Classic Literature": [
        "Pride and Prejudice", "Moby-Dick", "Crime and Punishment", "Jane Eyre",
        "Wuthering Heights", "Anna Karenina", "The Brothers Karamazov", "Frankenstein",
        "Dracula", "The Picture of Dorian Gray", "The Count of Monte Cristo",
        "Heart of Darkness", "The Scarlet Letter",
    ],
    "Horror": [
        "The Shining", "It", "House of Leaves", "The Haunting of Hill House",
        "Mexican Gothic", "The Exorcist", "Interview with the Vampire", "Pet Sematary",
        "The Fisherman",
    ],
    "Romance": [
        "Outlander", "The Notebook", "Beach Read", "Red White and Royal Blue",
        "It Ends with Us", "Persuasion", "Normal People",
        "Love in the Time of Cholera",
    ],
    "Young Adult": [
        "The Hunger Games", "The Perks of Being a Wallflower", "Speak",
        "The Book Thief", "Six of Crows", "The Fault in Our Stars",
        "Looking for Alaska", "Wonder", "The Giver", "An Ember in the Ashes",
    ],
    "Nonfiction": [
        "Sapiens", "Educated", "Into the Wild", "The Immortal Life of Henrietta Lacks",
        "A Brief History of Time", "Thinking Fast and Slow", "Man's Search for Meaning",
        "In Cold Blood", "Born a Crime", "Just Mercy", "The Warmth of Other Suns",
    ],
    "Poetry": [
        "Leaves of Grass", "The Waste Land", "Ariel", "Milk and Honey", "Howl",
    ],
    "Historical Fiction": [
        "All the Light We Cannot See", "The Nightingale", "Pachinko", "Wolf Hall",
        "The Kite Runner", "A Thousand Splendid Suns", "The Tattooist of Auschwitz",
        "Homegoing", "East of Eden",
    ],
    "Contemporary Fiction": [
        "Where the Crawdads Sing", "Little Fires Everywhere",
        "The Seven Husbands of Evelyn Hugo", "Klara and the Sun",
        "The Midnight Library", "Lessons in Chemistry",
        "Tomorrow and Tomorrow and Tomorrow", "Demon Copperhead", "Exit West",
        "A Man Called Ove",
    ],
}

# Books that get three reviewed logs each, so a book page's "Popular Reviews"
# has a genuine top three to rank rather than a single lonely review. Their
# like counts are set explicitly (see HOT_LIKE_COUNTS) so the order is obvious
# and never reshuffles between runs.
HOT_BOOKS = [
    "Beloved", "Dune", "The Left Hand of Darkness", "The Three-Body Problem",
    "The Dispossessed", "Slaughterhouse-Five", "Good Omens", "Rebecca",
    "The Brothers Karamazov", "Educated", "The Name of the Wind",
    "The Book Thief", "Pachinko", "A Thousand Splendid Suns", "Demon Copperhead",
    "The Immortal Life of Henrietta Lacks",
]

# (rating, review) per title, in descending order of enthusiasm — index 0 is
# the one that ends up top of the Popular Reviews ranking for hot books.
# Ratings live in 1.0-5.0 in 0.5 steps because that's the range the API's own
# ReadingLog schema accepts (ge=1), so nothing here is unreachable via POST.
REVIEWS = {
    "Beloved": [
        (5.0, "Sethe has been carrying the scar since the house, and the novel makes you understand that a haunting can be entirely internal and still completely literal. Every time I thought it was slowing down to make a point about history, it turned out to be about something much more private: what a mother will do to keep a promise to herself, and what it costs the child to be the reason. The last three pages are the best thing I have read this year, and I mean that about the writing and not the story — Morrison is doing something almost supernatural with the prose there, sentences that stop and restart the way memory does. It is dense in the way a dream is dense, and the second time through is immeasurably better than the first. Everyone says it is difficult. It is difficult in the way a bruise is difficult: not because the words are hard but because they land somewhere specific."),
        (4.0, "Dense in the way a dream is dense — I had to read chapters twice and the second time was better. Morrison is doing three things at once here (a ghost story, a mother-and-daughter book, and an argument about how the country metabolises its worst day) and she refuses to pick one."),
        (3.0, "I can see exactly why people revere this and it still wasn't for me. I kept waiting to be hooked the way I was by Beloved's more pulpy cousins. The prose earns it in the end, but I spent two hundred pages resisting."),
    ],
    "Dune": [
        (5.0, "The thing people forget is that the first half of Dune is a ghost story about a boy who can see the future and is terrified of it. Herbert builds an entire religion around not wanting to be loved, because the loved one will die. Everything after that is just the politics of a messiah who doesn't want the job."),
        (4.5, "Read it for the ecology and stayed for the mind-reading. Herbert invents jargon and then uses it as emotional pressure — you understand a character by the way they talk about water. The last hundred pages are one long chase and I couldn't put it down."),
        (3.5, "Enormous fun, and I say that as someone who is not normally a fantasy person. The world is invented with real rigour, but the interiority can be a slog when Paul is doing his Christ thing for the fourth chapter running. Read it for the planet."),
    ],
    "The Left Hand of Darkness": [
        (5.0, "The ice crossing is the whole book in miniature: two people who cannot read each other, forced into proximity, slowly developing a vocabulary. Le Guin never explains Gethen, she just puts you on it, and the ethnography of Estraven's world is the most useful thought experiment in science fiction — an entire civilisation organised around the fact that its members cannot commit to a promise until the coldest month ends. She is also quietly doing anthropology on our own world, and far more confident about that than about anything actually happening on the ice. The middle section, where Genly Ai is an honoured guest in a country that has abolished war, is Le Guin dismantling a century of easy assumption with no ceremony at all; the only thing that stops it being smug is that the person telling you about it is a pompous, prejudiced outsider who is gradually being wrong about everything. Light is only a metaphor for the first half and then it is a weapon, which is a very Le Guin move. The ending refuses to resolve the relationship in the way every part of you is hoping for, and it is right to. It is also a real novel about loneliness that happens to be set on another planet, which I think is why it has lasted."),
        (4.5, "I came for the pronouns and stayed for the politics. The middle section, where Genly Ai is a guest in a country that doesn't have war, is Le Guin quietly dismantling a century of easy assumptions. Also the first novel I've read where the snow is genuinely frightening."),
        (4.0, "Slow, strange, and completely worth it. Light is only a metaphor about halfway through and then it's a weapon. Ai is a really interesting narrator to be stuck with, because he's arrogant and we have to sit inside his blind spots."),
    ],
    "The Three-Body Problem": [
        (5.0, "The first half is a mystery novel wearing a physics textbook as a disguise — a secret military project, a series of impossible scientific questions, and a blinking three-body problem that will ruin your sleep. Then the book does something almost nobody in English-language sci-fi does and changes genre without asking permission."),
        (4.5, "Cixin writes hard SF with the pacing of a thriller. The Red Coast chapters are the best thing in the book: seven hundred years of scientists being burned for a theory they proved correctly. It's the great man vs the mob idea, except the mob wins for a while."),
        (4.0, "Excellent, though the middle does sag a bit once the physics gets technical. Worth it for the ideas alone — I'd read a whole book of nothing but Ye Wenjie and the sophons. The deuterium-bomb detonation on Jupiter is the kind of image people remember decades later."),
    ],
    "The Dispossessed": [
        (5.0, "Two planets, two kinds of utopia, and a physicist who cannot get a grant in either. The uranus transit is not a metaphor for the plot, it is the plot: the whole novel is about the gap between what a place promises and what it actually lets you do. Hearn is funny, too, which nobody warns you about, and the funniest passages are the ones where an anarchist scientist explains procurement law. What gets me is that Shevek's tragedy is not politics but credit — nobody will fund the work because he will not be humiliated by the people who fund it — and once you see that the book's whole arc is a man slowly accepting that a research programme needs administrators, the ending is a genuinely sad and completely earned thing. Read it for the walls, and read it slowly, and be ready to have the uranus chapter ruin your week."),
        (4.5, "The best argument for a book anyone will ever write. Nothing happens for three hundred pages, in the sense that Shevek goes from being a troublesome student to being a nuisance with a research grant, and it is the most eventful quiet novel I have read. Everybody should read this and then argue about it."),
        (4.0, "Worthy but the first hundred pages are a wall of unfamiliar nouns. Once I stopped keeping a glossary and let the world wash over me, the twin-worlds structure clicked and I couldn't look away. There's a line about a wall that made me put the book down for a minute."),
    ],
    "Slaughterhouse-Five": [
        (5.0, "The first line tells you the book is about the absence of a feeling, and then it spends 200 pages demonstrating it. Billy Pilgrim has the most useful disability in fiction — being unstuck from time — and Vonnegut uses it to make the Hiroshima bombing the least interesting thing that happens to him, which is exactly the point."),
        (4.5, "I resisted the jokes for a hundred pages and then realised they're the only way to hold the subject. 'So it goes' is doing the work of a whole meditation on the pointlessness of war, and the book is far more upsetting than it lets on. The book's children on the trampoline broke me."),
        (4.0, "Short, funny, and quietly annihilating. Rereading it after a decade, the sustained detachment is even more painful — Vonnegut can only show you the bombing from far enough away for you to bear it. The one issue: it assumes you already know about Dresden."),
    ],
    "Good Omens": [
        (5.0, "A theological thriller in which nothing happens and the universe is saved anyway. Crowley and Aziraphale's flat above a Soho bookshop is the funniest sustained setting in fantasy, and Pratchett keeps the whole thing grounded by refusing to take any of it seriously, including heaven."),
        (4.5, "I came for the jokes and stayed because it's secretly a serious novel about the failure of Heaven's PR. Every demon in it is a former angel who was cast out for being unreasonable. The Antichrist is a nice lad who mostly wants a job."),
        (4.0, "Charming, and it earns its ending, which is a high bar for a comic fantasy. The American South is used for jokes that have aged better than most. Adams's invented esoteric lore is a delight. Slightly overlong in the middle."),
    ],
    "Rebecca": [
        (5.0, "A novel about a woman who is never named, married to a widower, living in a house that still belongs to his dead first wife. du Maurier's control is terrifying: almost nothing happens, and the whole book is Manderley whispering. The last line is the best last line in English."),
        (4.5, "The first time I read this I was fourteen and thought it was a ghost story. It's actually about the destruction of a self by an environment that will not accept her as real. The women at Manderley and the men who run it are a two-sided portrait of English power that still lands."),
        (4.0, "Not really a mystery novel despite the reputation. It's a mood piece and the mood is being steadily starved of self-belief. I was a bit impatient with how often Max repeats himself, but du Maurier is doing that on purpose — the house is grinding him down too."),
    ],
    "The Brothers Karamazov": [
        (5.0, "Dostoevsky put the whole of Russian philosophy into a family dinner and then made each brother an argument you could put on a t-shirt. Alyosha is the reason it is a novel and not a debate: he is held in a monastery for the whole book and is the only person anyone is kind to, and you understand that the rest of it is happening in a world that does not have him. 'The Grand Inquisitor' is the greatest chapter ever written and I do not say that often. Ivan's poem about children — the thing children suffer that cannot be redeemed — is genuinely upsetting, and Fyodor's obscenity is funnier than anything has a right to be in a book about the death of faith. Zosima's teachings did nothing for me emotionally even though the prose is clearly working harder than it needs to, which I suspect is a real flaw and not mine. Dmitri's last scene, where he stops being funny and becomes a person in front of his brother, is the moment the whole book is working toward. Read it long, and read it in order — the brothers have to take turns."),
        (4.5, "Long, argumentative, and the only book I've ever read that made me want to argue back with a fictional person. Ivan's poem about children in The Grand Inquisitor is a genuinely upsetting piece of writing, and Fyodor's obscenity is funnier than it should be in a book about the death of faith."),
        (4.0, "The first 400 pages are a pleasure and the last 300 are a theological seminar, but Dostoevsky has earned the seminar. Zosima's teachings did nothing for me emotionally even though the prose is clearly working. Read it for the characters; the philosophy is the excuse they use to talk to each other."),
    ],
    "Educated": [
        (5.0, "The scene with the older man in the car — the one where Westover realises her life has been kept from her by people who love her — is worth the entire memoir. Tara describes getting an education as a form of violence, and she's not being dramatic; the memoir is precise about how much damage a college degree did to her capacity to trust her own mind."),
        (4.5, "I read this right before finishing my own memoir and it made me extremely nervous. It's the rare memoir that's actually about something rather than about the author's gift for being likeable. The footnotes matter; she circles back to them in the afterword and it changes the whole shape of the book."),
        (4.0, "Strong, and the childhood chapters are astonishing. The last 100 pages are a little tidy for my taste — trauma reconciled in a way I didn't find convincing. But 'gaslighting' has never been better illustrated, and the jaw-dropping midpoint revelation is worth the whole climb."),
    ],
    "The Name of the Wind": [
        (5.0, "A university city, a dockside murder nobody investigates, and a boy who has been performing 'mouth of a cripple' his whole life. It's the rare epic fantasy where the hero's real skill is lying, and the frame — a man in an inn telling a chronicler the truth while lying constantly — is doing more work than the magic system ever does."),
        (4.5, "Rothfuss writes the way a musician plays, and Kvothe's voice is so consistent that you hear it in your own head by hour twenty. Denna is the best character in the series and the University sections are genuinely fun. The framing device takes a while to reveal itself, and then the book gets much sadder and much better."),
        (4.0, "Beautiful prose, uneven plotting. The first half of the University arc is wonderful and the Denna business is a slog, and I could see exactly where the seams were. Still the best magic system I've read, mostly because the cost of magic is real and comes out of your body."),
    ],
    "The Book Thief": [
        (5.0, "Narrated by Death, which should be unbearable and is instead the only thing that could carry this book. Liesel steals books and her brother steals bread, and Zusak's real subject is the ordinary decency that survives everything Germany did to the people who lived there. 'The rehearsal' chapter is a masterpiece and I will not be elaborating further."),
        (4.5, "It's a Schindler's List with a child narrator, and the trick that works is that the narrator is also the one watching. Every time Death lists a death, he follows it with what they were doing just before, so the list becomes a list of interruptions. It's manipulative and I fell for it completely."),
        (4.0, "Bigger than I expected and not in a bad way, though the foreshadowing is extremely loud — Death announces things six pages early. The prose leans very hard on short declarative sentences, which I found tiring after two hundred pages. Still, the last twenty pages are extraordinary."),
    ],
    "Pachinko": [
        (5.0, "Four generations of a Korean family in Japan, and the title object is the one thing that never gets explained. Lee's real achievement is that the grandmother's fish sauce, the son's jazz, the daughter's piano are all the same story: a family making a life in a place that will never quite let them. The rhizome at the end tells you how to read it."),
        (4.0, "Quietly devastating and very long. Sunja's first chapter is one of the great things in contemporary fiction, and then the book gives each of her descendants a chapter so the pain compounds instead of repeating. I struggled with the daughter, Minja, whose sections are the weakest."),
        (4.5, "I resisted this one because a book about systemic racism in Japan sounded like a lecture and it turned out to be a novel about furniture. The domestic scenes are so particular — the specific shame of a job that is skilled and therefore unbearable — that the history gets in on the sly. The way it ends, circling back to the house, wrecked me."),
    ],
    "A Thousand Splendid Suns": [
        (5.0, "Two women who never meet, married in the same arrangement to the same escalating husband, and the novel makes you wait 300 pages for them to collide. Mariam's chapters are so quiet they hurt; Lail's are melodrama by comparison, and then the last act makes you realise Hosseini knew that the quiet one was going to win."),
        (4.0, "The obvious structure — two women, same husband, converge — is a formula and it works anyway. Hosseini can write a bazaar. But it's sentimental, and the reconciliation between the two women is rushed in a way the 300 pages of setup don't earn."),
        (4.5, "I couldn't put it down. What gets you is the ordinariness of the violence: it's always a Tuesday, it's always someone going to the market. Mariam eating dirt is the detail I can't get rid of. Slightly too tidy at the very end but I'll forgive it a lot."),
    ],
    "Demon Copperhead": [
        (5.0, "Dickens with a female narrator in Appalachia and an indictment of the foster system instead of the workhouse, and Barbara Kingsolver is very funny doing it. The Dooling boys are a genuinely great set of antagonists, the football chapters are a joy, and the last section — Copperhead on trial, telling his own story — is a courtroom novel nobody has written since To Kill a Mockingbird."),
        (5.0, "There is a chapter about getting a driving licence that is more accurate than most novels about young adulthood. The voice holds up for 550 pages. Whatever you think of the romance subplot, the indictment of religious foster care is written with real anger and real evidence."),
        (4.5, "Long and worth it. My only quibble is that it is a little too kind to the birth mother, who gets an ending I did not buy. But the depictions of poverty here are unsentimental in a way that felt almost radical."),
    ],
    "The Immortal Life of Henrietta Lacks": [
        (5.0, "Reported non-fiction that reads like a heist novel: the story of a biopsy that went wrong, a family that didn't know for decades, and a scientist whose career was built on cells he obtained by asking. Skloot never lets you forget the tissue came from a person, and the chapter where Rebecca Skloot explains the vocabulary to Henrietta's family is the best page in the book."),
        (4.5, "The structure — Deborah's voice, then Skloot's — is a risk that pays off, because Deborah is funnier and blunter than the reportage. The 1951 chapter is tense in a way nonfiction rarely is. It does drift into a second act about Skloot's own life, which I found less interesting than the first."),
        (4.0, "Extremely well researched, and the ethics are handled with more care than most books on this subject manage. The HeLa section alone justifies the cover price. A little repetitive in the middle and the family members are sometimes more archetypal than real."),
    ],
    # --- everything else: one or two reviews, enough for a believable shelf ---
    "To Kill a Mockingbird": [
        (4.5, "Atticus Finch is the reason this still matters — a man who actually loses, and is still right about most things, and says so knowing it. Lee structures it as a child's understanding slowly catching up to an adult's, and the trial scene is as effective now as when it was written."),
    ],
    "Mrs Dalloway": [
        (4.0, "A single day in June and two people who used to be everything to each other. Woolf moves between Clarissa's party and Septimus's collapse by the sound of a distant plane and a change of tense, which should be showing off and instead is the whole novel. Septimus's death is not a plot twist; it's a fact arriving on schedule."),
        (2.5, "Everyone tells me to read this and I have now read it twice and it's not for me. I found the character with the shell shock genuinely upsetting rather than moving, and Clarissa's fussing about party logistics felt like preciousness. The prose is gorgeous and I kept noticing it instead of the book."),
    ],
    "The Great Gatsby": [
        (3.5, "Fitzgerald does the impossible trick of making a story about a man you can see through still work as a tragedy. Nick is the whole book — a narrator chosen precisely because he is not clever enough to understand Gatsby. Worth reading for the last thirty pages alone, which contain the best paragraph in American fiction."),
    ],
    "One Hundred Years of Solitude": [
        (4.0, "Generational repetition as a disease, and the prose has that same circular feel, so long that you start recognising sentences you read fifty pages ago. Hard going, but the last century — the flood and the banana massacre — is worth everything you put in."),
    ],
    "The Catcher in the Rye": [
        (3.0, "I did not get along with Holden and I think that's the correct response to a book that wants you to distrust your own reactions. Salinger writes a teenager brilliantly and then spends 200 pages explaining how brilliant he was. Fine for a 17-year-old, insufferable for a grown adult."),
    ],
    "Middlemarch": [
        (4.5, "Not a plot, really — a set of people making small consequential decisions in a provincial town while the reform bill passes somewhere in the background. Eliot's real subject is how narrow a life can be and how much it can still contain, and she never condescends to her characters, which is the hardest thing in the nineteenth-century novel. The famous last two sentences are earned, which is very rare, and the book earns them partly by refusing to end on a note of summary. Dorothea's second marriage is the single most convincing depiction of intellectual snobbery in fiction. Casaubon is a great character: a failed scholar who has decided that his failure is a kind of sanctity, and Eliot writes him with a sympathy that makes me actively uncomfortable, which I think is the point. Lydgate's decline is the best account of moral drift I have read anywhere. And the famous marriage plot — Lydgate and Tertius — is almost an aside, which is how you know the book is really about something else."),
    ],
    "Norwegian Wood": [
        (3.5, "Grief and self-harm and a lot of very specific 1960s Tokyo. The middle section where Toru and Naoko are simply sitting in her apartment not talking is the most honest depiction of depression I've read in a novel. Watanabe's women are gorgeous and slightly unreal, which I suspect is the point and I didn't fully buy it."),
    ],
    "The Remains of the Day": [
        (4.5, "Ishiguro can do a great deal with a single crack in a facade."),
    ],
    "The Bell Jar": [
        (4.0, "Esther Greenwood wants to be a poet and keeps almost becoming one before something knocks her down, and Plath writes the ambition as a kind of lightness that isn't healthy. The book got a lot more frightening to me as I got closer to the age she was when she wrote it."),
    ],
    "Atonement": [
        (4.0, "Brannion's crime in the first half is so casually awful that the novel earns its own ambitions afterwards. McEwan's shift into wartime London is good, and the ending is a formal trick that I admire and would rather not have been sprung on me."),
    ],
    "Wide Sargasso Sea": [
        (4.0, "Rhys's great idea is to give the Rochester of Jane Eyre a whole life before the reader meets him, so that by the time he locks the door you know exactly what he's closing off. Antoinette's descent is written as a horror story about a woman being told her vision is madness."),
    ],
    "Neuromancer": [
        (4.0, "Either the source of every cyberpunk cliché or the reason they work."),
    ],
    "Snow Crash": [
        (3.0, "Fast, dated, and cleverer underneath than it looks."),
    ],
    "Hyperion": [
        (4.0, "Seven pilgrims telling their stories on a pilgrimage to the world-shaker, and the structure means you're always anticipating someone else's reveal. Cant's ship and Kepler's blackmail are the two I remember. Simmons can be overwritten but here it's a fair trade for the ideas."),
    ],
    "The Martian": [
        (3.5, "Accurate, funny, and Weir's love of procedure is the whole book."),
    ],
    "Fahrenheit 451": [
        (4.0, "The bit everyone remembers — Bradbury imagining the future and getting a fireman right — is a real achievement. What's more interesting is the last quarter, where it becomes about people who memorise books and why that matters. 'It will not be the fire. It will be what we do with the fire.'"),
    ],
    "Brave New World": [
        (3.0, "The opening chapters are still some of the best writing in the genre."),
    ],
    "A Fire Upon the Deep": [
        (3.5, "The second half is doing real work; the first is very Vinglish."),
    ],
    "Children of Time": [
        (4.5, "Lévi is the best uplifted character in science fiction because he is a biologist who invents a social contract and calls it a religion, and Tchaikovsky is honest enough to let the cost of that religion be the ending rather than the prologue. The spiders are genuinely unsettling without ever being the point — they are what happens when a species with that much time and that much intelligence finally has a problem it can spend a century thinking about."),
    ],
    "Ancillary Justice": [
        (4.0, "An AI with thousands of bodies telling its own murder story in the past tense, which is a great structural choice because the reader doesn't know for three hundred pages that they are the weapon. Breq's identity crisis is the best portrayal of a dissociative episode I've read."),
    ],
    "Solaris": [
        (4.0, "A station orbiting a planet that gives you what you secretly want, and what it gives Kelvin is his dead wife, imperfectly remembered. Lem does in a hundred pages what most writers would need a trilogy for. The novel ends ambiguously and I think deliberately — a scientist confronted with a miracle chooses paperwork."),
    ],
    "The Hobbit": [
        (4.5, "A proper fairy tale that happens to have a sophisticated moral about greed at its centre, and it's a fraction of the length of the Lord of the Rings so you can finish it in three evenings. Tolkien's riddles and songs are a delight, and the unexpected deaths of a cheerful, competent character still land."),
    ],
    "A Game of Thrones": [
        (3.0, "A magnificent world, and I never once cared who lived."),
    ],
    "The Way of Kings": [
        (4.0, "The Bridge Crews and oaths-about-eyes is the most original magic system I've read this century, and the first 300 pages are some of the best genre writing going. Sanderson is very good at battle, less good at women, and Kaladin's backstory is worth the slog. Bridge Four, of course. Always Bridge Four."),
    ],
    "American Gods": [
        (4.0, "Gaiman at his best when he's writing asides. Shadow travelling the country with a dead man for a companion and accidentally assembling a pantheon of New Gods is a great high-concept road novel, and the Chicago-meets-Heaven ending earns a lot of it. Odin's whole introduction is legendary for a reason."),
    ],
    "Piranesi": [
        (4.5, "Ninety pages, and I read it in one sitting at 2am and then had to sit in the dark for a while. A man in a house of statues and tides who catalogues it as a scholar, and the revelation about who's been writing in his journals is one of the best twists in years. Read it fast, it doesn't survive being picked over."),
    ],
    "The Song of Achilles": [
        (4.0, "Patroclus narrating a life from beyond the grave, mostly the love story. It's a retelling that adds about two genuinely new things: Patroclus's fear, and Achilles as someone who is loved rather than just worshipped. The Iliad is mostly better, but this made me want to reread the Iliad."),
    ],
    "Jonathan Strange and Mr Norrell": [
        (3.5, "Clarke writes footnote-sized jokes for 800 pages and eventually earns a climax. Extraordinary texture, and the invented English idiom of the period is hilarious and convincing. But the actual plot is baroque and shapeless and I occasionally wanted to shout at everyone."),
    ],
    "Uprooted": [
        (4.0, "Novik writes the kind of folk tale where the forest is a character with an opinion. Agnieszka grows into her gift, and the wood's courtierly menace is a great pairing with the country she's stuck in. The first half is a better story than the second, but it's all readable."),
    ],
    "The Night Circus": [
        (3.0, "Morgenstern's prose is so beautiful that the plot is easy to forgive for not existing. Two magicians, an instruction never to interfere, a competition they forget they entered. Lovely, airless, and hollow — a beautiful room with nothing in it. Not for me, but I understand the adoration."),
    ],
    "Gone Girl": [
        (4.0, "The first half is a thriller and the second half is a genuinely uncomfortable book about what marriage looks like from the inside when the love has curdled. Flynn nails the voice of the woman people think is the villain. Ending divided a room and I was in the room for 'ambiguous on purpose'."),
        (3.0, "Enormously fun, extremely well plotted, and I found the ending cheap. The last 50 pages are a lot of neatness — a diary found, a twist, a tidy double-guest sequence — that undoes some of the nastiness. Worth reading for the first 200, which are close to perfect."),
    ],
    "The Girl with the Dragon Tattoo": [
        (3.5, "A 700-page Swedish procedural about a hacking-disabled investigation and a family in a mill town with a secret, and it earns the length. Lisbeth is one of the great antiheroines. Slightly silly title, genuinely exciting plot."),
    ],
    "And Then There Were None": [
        (4.0, "The template for the entire genre and still a tight little machine. Ten people, an island, a nursery rhyme — and Christie lets you solve it, which is rarer than people think, because the red herrings are real herrings and not just noise."),
    ],
    "The Silent Patient": [
        (3.0, "The two timelines are the best thing here: a woman who has stopped speaking and a man narrating his own therapy, and the two start saying exactly the same things. Then the third act makes the narrator so obviously guilty that the mystery evaporates. Excellent opening, over-explained ending."),
    ],
    "The Big Sleep": [
        (4.0, "Chandler at his most fluent, and the most fun you'll have reading about murder. Nobody in this book is entirely honest, including Philip Marlowe, and the plot is a comic strip. The word 'heft' is used properly here, which is a test most writers fail."),
    ],
    "In the Woods": [
        (4.0, "A murder in a Dublin park and a boy who was found in the same park twenty years earlier, and Tana French is very good on the thing that makes it work: the second investigation is conducted by the suspect, who has to look at his own childhood from the outside. The interview scenes are the best writing in the book."),
    ],
    "The Talented Mr Ripley": [
        (4.0, "Highsmith writes sociopathy as a skill set. Tom's envy is described without any moral commentary at all, which makes it far worse. The first half is a slow poisoning; the second is a thriller about a man who has committed the perfect crime and then can't stop buying things."),
    ],
    "Sharp Objects": [
        (3.5, "Gillian Flynn again, and this time it's a small-town plod with a mood like wet newspaper. The reveal is predictable about forty pages out. The prose is so good I'd still recommend it — a great title sequence, a menacing set of suspects, and a genuinely traumatised protagonist."),
    ],
    "The Name of the Rose": [
        (4.0, "The mystery is a red herring and the abbey labyrinth is the real book."),
    ],
    "The Postman Always Rings Twice": [
        (4.0, "A drifter and a café owner, a bad marriage, and a plot that is basically the pulpy core of Double Indemnity in rural California. Cain's prose is cheap and brilliant and the ending is the exact opposite of Resurrection. Minor only because it's so short you can be done by lunch."),
    ],
    "Pride and Prejudice": [
        (4.0, "I'd read it in high school and been bored by it, then read it again at 30 and found that Darcy's letter works. The reason it's one of the great books is that it's actually about money and property, and the courtship is the vehicle. Everyone quotes the first line and almost no one survives the second half without losing interest — I nearly did."),
    ],
    "Moby-Dick": [
        (3.0, "Ahab is one of the great monsters of literature and this book is not really about him — it is about the crew, the cetology, and a narrator who has decided to be present for all of it. I thought the cetology chapter was wonderful and the last third a slog, and I stand by that: the book is at its best when it is a book about whaling, taxonomy and the inside of men's heads, and at its worst when it is a chase scene. The problem is that the whale spends the middle of the novel dead. Ishmael's 'From hell's heart I stab at thee' speech is the emotional peak of the entire book and it arrives about two hundred pages before the climax, and then the climax is a great deal of shouting. But the Pequod is one of the great vessels in fiction, the crew are a real ensemble rather than a mob, and the cetology chapter is doing something genuinely wonderful with the fact that a book can be organised around the act of looking at things. Read it for Ishmael's slow accumulation of small resentments, which is what the whole novel is built on, and be patient with Ahab."),
    ],
    "Crime and Punishment": [
        (4.5, "A poor young man reasons his way into murdering a pawnbroker and then spends 500 pages being slowly destroyed by it. Dostoevsky makes you complicit — you follow the argument because it's good. The dream sequences and the conversations with Porfiry are unmatched. Sonya's scene on the riverbank is the whole novel's heart."),
    ],
    "Jane Eyre": [
        (4.0, "A first-person narrator who tells you honestly and flatly that she wants to be equal to Rochester and a free person, in a book that's about acquiring both at once. The Thornfield drawing-room is a great set and Bertha is the best locked-room problem in fiction, mostly because the answer is 'in the attic' and the book won't say for 300 pages."),
    ],
    "Wuthering Heights": [
        (5.0, "The most structurally audacious novel in English and it barely holds together, which I now think is the point. There are two nested narrators — Lockwood, a snooty Liverpudlian tourist, and Nelly, the housekeeper who was in the middle of it and lies about almost everything she saw. Neither is a reliable witness, and Heathcliff is the only character ever described directly, usually by people frightened of him. Emily Bronte makes the frame narrators as furious as the book itself: you can feel her daring you to look away. Nelly keeps saying she hates the castle and then describing it for forty pages. The violence is real and is also the least interesting thing in the book; what I cannot put down is the grief, which runs through the foundations and outlasts the plot. Cathy and Heathcliff are not a love story, they are a structural joint, and the ending — the child looking out over the moors, waiting — is the only place the novel is ever quiet."),
    ],
    "Anna Karenina": [
        (4.0, "Two stories: a widow's affair and a man's search for meaning, cut in blocks of varying length, and the blocks are constantly better than the through-line. 'All happy families are alike' is one of the great opening lines and Tolstoy then spends four hundred pages proving it. Levin is the character I'd keep."),
    ],
    "Frankenstein": [
        (3.5, "Not a horror story at all — it is about responsibility."),
    ],
    "Dracula": [
        (3.5, "The best horror in it is Mina's diary."),
    ],
    "The Picture of Dorian Gray": [
        (4.0, "A man trades his face for his soul in a novel that's 70% aphorism, which I found close to unbearable and which I still quote from. Wilde's picture of Victorian respectability is savage. The plot does stall for a long time in the middle, and Lord Henry is fascinating rather than likable, which I think is the point."),
    ],
    "The Count of Monte Cristo": [
        (4.5, "Justice or revenge, the book cannot decide, and both threads are enormous. The first half builds a very specific grievance with more patience than most modern novels would, letting you watch the world of the Edmonds and Fernand collapse from above and from a long way off, and then the second half is a thousand pages of a man systematically ruining the people who wronged him, which is far funnier and more fun than I expected. Dantès's cruelty is a great change of pace from the wounded innocent of the opening, and the book knows it — by the time he is manipulating a family into destroying itself, he has stopped being the hero and become the plot. The sections in Paris society that nobody wants to read are also the ones I remember, because they are about waiting. Read it for the shape rather than the thrills: this is a novel about the difference between suffering something and being permitted to do anything about it, and it is far more interested in that question than in whether Dantès deserves his ending."),
    ],
    "Heart of Darkness": [
        (3.5, "A river boat and a man who is both reporting on Kurtz and becoming him. The famous 'the horror' line is famous because Conrad earned it, and the novella is genuinely unsettling about the claim that civilisation is worth anything. Very heavy going in the middle and the frame device is a bit of a chore."),
    ],
    "The Scarlet Letter": [
        (2.5, "A book I have stopped defending. Dimmesdale's guilt is legible to me as a man standing in a market square in front of everyone for seven years without moving, which kills the drama. Chillingworth is a great character and the whole book is about him, and I think Hawthorne knows it and doesn't quite mean it to be. I can see the craft, I just didn't feel it."),
    ],
    "The Shining": [
        (3.5, "Jack Torrance is one of the best written men in horror — funny, self-aware, and a completely credible monster. King nails the writer's block sections and the Overlook as a physical place. The ending is a famous weak patch and the doc-pages trick is a gimmick, but the middle third is as frightening as anything I've read."),
        (2.0, "I know it's a classic and I don't care. The audiobook is just a long 400-page jam of the same man describing the same place, the prose is overwrought to the point of parody, and the ending undoes whatever the middle achieved. The Shining is a great idea that King takes four hundred pages to explain."),
    ],
    "It": [
        (4.0, "A book that is honestly about being eleven, and gets that exactly right — the lash of terror you can't articulate, the sense that adults are negotiating rather than helping. King writes Losers' Club in a way that makes the genre embarrassing in the best way. It's long and Derry is a real place, which is most of the trick."),
    ],
    "House of Leaves": [
        (3.5, "A doctoral dissertation about a documentary that may not exist, formatted as the documentary's academic analysis. Zdarsky's typography is genuinely the content at times. Also, an actual family tragedy at its centre, which sneaks past you. The first half is the best of it and the second is a braindump, but the concept is unmissable."),
    ],
    "The Haunting of Hill House": [
        (4.0, "The house never lies, and that is exactly the problem."),
    ],
    "Mexican Gothic": [
        (3.5, "A 1950s drug trip by rich Westerners to a decaying mansion in_verifyland Mexico, and Moreno-Garcia is a great writer of disgust — the physical descriptions of the house are repellent in a way that functions as characterisation. Slow, dripping, and genuinely scary, though the last act gets a bit cosmic."),
    ],
    "The Exorcist": [
        (3.0, "Famous for the best-documented possession in cinema and less good as a novel — Blatty's prose is workmanlike, and the novel is 90% scene-setting before Karras starts doubting his own faith. The Willis detail is great and genuinely the most frightening idea in the book. Also the first thing I ever read with genuinely horrible body-horror beats."),
    ],
    "Interview with the Vampire": [
        (4.0, "A monologue to a notebook, two thousand years of vampire, and the period dressing is genuinely fun. The best horror here is existential — 'was the interview real?' — and Louis's gradual admission that he wants to die is better than anything the film version does with him. N Interview has an argument about what the interview is."),
    ],
    "Pet Sematary": [
        (4.0, "The one where Louis Creed buries the cat and can't leave the spot alone. King writes grief and domestic friction with equal intensity and the reunion rig scene is the most upsetting thing in his catalogue. Slightly relentless, and the last 20 pages are a cheat, but the middle is airtight."),
    ],
    "The Fisherman": [
        (2.0, "I want to be careful here because people clearly love it, but for me this was an endurance test: two fishermen, an eldritch thing in the harbour, a 500-page slog of ritual and dread with no relief. The imagery is striking and the dread never escalates into anything I could feel. Perfect as a mood, too slow as a story."),
    ],
    "Outlander": [
        (3.5, "Superb eighteenth-century Scotland, tedious everything else."),
    ],
    "The Notebook": [
        (2.0, "Technically flawless and emotionally fraudulent."),
    ],
    "Beach Read": [
        (3.5, "Two different books wearing the same jacket, and I liked both."),
    ],
    "Red White and Royal Blue": [
        (3.5, "A good slow burn that handwaves very hard about the palace."),
    ],
    "It Ends with Us": [
        (2.5, "I think Hoover is genuinely trying to make a book about how abuse gets romanticised and a lot of readers are opting for the romance anyway. Lily and Ryle are a great study in the mechanism. But the plot is doing something dishonest to a reader's goodwill and the ending feels like a decision made for sales reasons. YMMV, apparently, very much so."),
    ],
    "Persuasion": [
        (4.0, "Austen at her most wry, and Wentworth's letter is worth the whole book."),
    ],
    "Normal People": [
        (3.0, "Two brilliant characters and a plot that keeps nearly happening."),
    ],
    "Love in the Time of Cholera": [
        (4.0, "Fifty years of Florentino's letters to a woman he has been silently in love with for most of a century, and that's the entire plot. The plot device is silly and the book is not — Garcia Marquez writes decades of unrequited longing as a form of grief, and the cholera dream at the end is a shock. The ending is disgustingly romantic and I loved it."),
    ],
    "The Hunger Games": [
        (3.5, "Propulsive, and better on spectacle as politics than on Katniss."),
    ],
    "The Perks of Being a Wallflower": [
        (4.0, "Letters from an anxious fifteen-year-old that somehow get the whole texture of adolescence right, including the specific embarrassment of caring too much and saying so. Chbosky's lightest-touch writing carries real weight — the final letter, four hundred pages of him, and it breaks me every time. The 1990s are not incidental, they're the point."),
    ],
    "Speak": [
        (4.0, "A book that treats a teenage girl's silence as an actual linguistic absence, and gets the adult response exactly right: everyone talks around it, and the talking is what traumatises her further. Laurie Halse Anderson is enormously good at short books. The final speech is earned."),
    ],
    "Six of Crows": [
        (4.0, "Six narrators, all distinct, and a heist plot I respected without following."),
    ],
    "The Fault in Our Stars": [
        (3.5, "A love story between two teenagers with cancer, which I read at exactly the wrong age and then again at exactly the right one. Green's first-person is a masterclass in telling you something small and enormous in the same breath. My complaint is that Hazel is a joke-_cracking machine in a book about being ill, which I never fully bought."),
    ],
    "Looking for Alaska": [
        (3.5, "Perfect on being sixteen, overstays itself by forty pages."),
    ],
    "Wonder": [
        (3.5, "R.J. Palacio never makes it a pity party, which is the best decision."),
    ],
    "The Giver": [
        (3.5, "Short, neat, and quietly suspicious of its own moral."),
    ],
    "An Ember in the Ashes": [
        (4.0, "Taha has a scar and a life story that explains it, and the second book is a prequel that goes all the way back to the massacre and explains where the scar came from. Tahir's fantasy is invisible — no portals, just historical trauma as a magic system. Chapters written in second person for the massacre are an extraordinary gamble that pays off."),
    ],
    "Sapiens": [
        (3.5, "A great provocation with a thin patch of evidence underneath it."),
    ],
    "Into the Wild": [
        (4.0, "The best hitchhiker-into-the-Bushes story ever told, and Krauser is careful enough not to turn Chris McCandless into a martyr, which is remarkable restraint. The Alaskan chapters are the best survival writing in American nonfiction. Slightly snobbish about the people who tried to help him, and the 'hobo ethos' business is a bit much."),
    ],
    "A Brief History of Time": [
        (3.0, "A genuinely good explanation of black holes and the big bang, and an extraordinarily bad explanation of everything else. Hawking is too charmingly vague about the philosophical questions — 'we don't know' is doing a lot of work. The illustrations carry a book it shouldn't need carrying. Read for cosmology, skip for meaning."),
    ],
    "Thinking Fast and Slow": [
        (3.5, "Gave me a vocabulary for cognitive bias, which I've been using for a decade. But the replication record on a lot of these priming studies is bad, and Kahneman himself acknowledges it in later work. The chapters on overconfidence and the two-system framing hold up best. The professor-endorsement sections are the most memorable and the least rigorous."),
    ],
    "Man's Search for Meaning": [
        (4.0, "Two short halves: a compressed account of a Nazi concentration camp, and a very short account of logotherapy, a therapy nobody has ever heard of that the author invented after surviving one. The second half is as thin as self-help always is, but the first half is a hundred pages of writing at the absolute limit of what prose can do. Irreplaceable."),
    ],
    "In Cold Blood": [
        (4.0, "Capote refuses to explain them, which is why it is still the model."),
    ],
    "Born a Crime": [
        (4.5, "A clown in a man-child, or a man-child in a suit, and Noah writes the gap between them with an intelligence that is frankly embarrassing. The chapter where he is beaten by a security guard and a white man who could have intervened doesn't go where you expect. He is a great narrator because he's always watching himself."),
    ],
    "Just Mercy": [
        (4.0, "Stevenson is scrupulous, which is what makes the cases land."),
    ],
    "The Warmth of Other Suns": [
        (4.5, "Three people who left the American South during the Great Migration, told in interlocking sections across sixty years, and Wilkerson's structure makes three individual lives add up to an argument about the century itself. A third of the book is Ida, who is the most interesting person I have read about in years and whom the other two strands exist to give context to. Greta is the most painted, which is the one place the book is a little too clever — her sections are so carefully composed that you occasionally catch the author admiring them. But that is a small price. What this book does that almost nothing else does is make you understand migration as an economic fact and an emotional catastrophe simultaneously, and it does it by refusing to make any of the three into a case study. The prose is dense, sometimes hard going, and completely trustworthy. The final section, where the last of them is moved by something she has been told about the other two, is worth every page before it."),
    ],
    "Leaves of Grass": [
        (4.0, "Whitman in a whirlpool: 'I am large, I contain multitudes' is either a great line or a great piece of marketing depending on your mood. There are poems here that genuinely soar and stretches where he's repeating himself. Read 'Song of Myself' as one continuous piece and don't read it out loud in public, which I did once."),
    ],
    "The Waste Land": [
        (3.0, "Famous, quotable, and I needed a guide."),
    ],
    "Ariel": [
        (4.5, "Sixty-three short poems, a bare handful of words each, and it is the most devastating thing in this list. 'Edge' is six lines and about as perfect as a poem gets. Read it in one sitting and then wait a day before you talk about it. The mushrooms are doing something I still don't think I've fully understood."),
    ],
    "Milk and Honey": [
        (2.5, "Every page is beautiful and not one of them surprised me."),
    ],
    "Howl": [
        (4.0, "Ginsberg screaming a drug-fueled indictment of America at the top of his lungs, and it's genuinely transgressive in a way that fifty years on is hard to feel — but 'I saw the best minds of my generation destroyed by madness' is still a hell of an opening line. Read the footnotes; the disclaimers about obscenity are their own kind of history."),
    ],
    "All the Light We Cannot See": [
        (4.5, "A deaf French girl and a German boy with a lightbulb, in occupied Saint-Malo, and Doerr is very good on the specific sensory texture of being a child navigating an adult catastrophe — sound, smell, the direction of a rifle. The braided structure earns its alternation. The last thirty pages are short of extraordinary, which is the only flaw."),
    ],
    "The Nightingale": [
        (4.0, "Two sisters in occupied Paris, one a nurse and one reckless, and the novel is clear-eyed about the fact that bravery and stupidity look identical at seventeen. The historical detail is well researched. It slips into genre-thriller in the last third and the ending is a touch neat, but the first two hundred pages are excellent."),
    ],
    "Wolf Hall": [
        (4.0, "Thomas Cromwell narrating the downfall of Thomas More, and Mantel writes the entire thing in the present tense so that the past feels like it's happening to the reader. It's dense, politically dense, and the prose is magnificent. Hilary Mantel is very good on the specific exhaustion of serving a king who changes his mind."),
    ],
    "The Kite Runner": [
        (4.0, "A boy who betrays a friend in Kabul, a redemption arc over thirty years, and Hosseini writes Afghanistan with real specificity. The first 100 pages in the alley are among the best child-perspective writing in English. The second half strands its heroine in a way I found genuinely upsetting, which I think was the intent."),
    ],
    "The Tattooist of Auschwitz": [
        (4.0, "A book about a man's tattoo, a woman who works in the camp, and a romance whose two halves meet in a therapy session in the present day. Heather Morris came at this from survivor interviews and the research shows — she has a knack for two-sentence exchanges that reveal everything. Less literary, more effective."),
    ],
    "Homegoing": [
        (4.0, "Two half-sisters, one in Ghana in the 18th century and one in America in the 20th, and the chapters braid rather than alternate. Yaa Gyasi writes violence with restraint and the structure means you get about 20 chapters of a story you then see reconnect. Devastating, and the baseball at the end is worth the whole thing."),
    ],
    "East of Eden": [
        (4.5, "A hundred pages of a man explaining his theory of good and evil to his children, and then five hundred pages proving it right. Steinbeck's Salinas is a fully realised world with its own weather, its own labour economy and its own class of people who lose everything in a single season, and the two fathers — one monstrous, the other monstrous in the other direction — are the best characters Steinbeck wrote. Cathy comes close to ruining the book and doesn't, because even in her we can see she is describing rather than living, which is the terrible thing about her. The flood chapters are a masterclass in what a novel can do with patience: nothing happens except water rising, and then everything happens. The book is openly interested in whether time's structure can be argued with, and you do not need to agree with Steinbeck about the 1950s to find it extraordinary. Adam Trask is a much better character than he has any right to be, and the ending — the family assembled at last in a place that is neither Cain's nor Abel's inheritance — earns everything before it."),
    ],
    "Where the Crawdads Sing": [
        (3.0, "A beautiful, isolated marsh girl and a boy who isn't good enough for her, told partly through an academic and partly in the girl's own voice, and the two registers don't quite fit each other. The last act is a mystery box office office-hours. I loved the character of Kya and was unmoved by the plot, which is a weird ratio to finish at."),
    ],
    "Little Fires Everywhere": [
        (4.0, "Four families in a Connecticut town and a baby in custody, and Celeste Ng is very good on the specific silence of a town that looks after itself. It's structurally a coincidence-fest and the coincidences are unapologetic. The two teenage girls are a great, funny double act and I was sorry to leave them. The final section is a brass knuckle."),
    ],
    "The Seven Husbands of Evelyn Hugo": [
        (3.0, "A dying Hollywood star gives interviews for a memoir nobody asked for, and the setup is a great, mysterious one. The problem is that the interviews are ashtray-thin and the actual story is the one the narrator is telling. Great fun, structurally a cheat, and a lot of readers clearly loved it more than I did."),
    ],
    "Klara and the Sun": [
        (4.0, "An artificial friend watches the family that bought her, and Ishiguro restricts himself to what she can actually observe from a windowsill, so the whole book is full of a child's misreading of adult life. The ambiguity about whether Klara is special or just well-made is handled beautifully. The last section is sadder than it needs to be, or exactly as sad as it needs to be."),
    ],
    "The Midnight Library": [
        (2.5, "A woman gets to try every life she didn't live and learns she's fine as she is, and the mechanics are a great idea defeated by the ending. It's a kind book with a genuinely bleak premise and Haig keeps trying to make the existential conclusion reassuring. I read it for a mate having a bad year and mostly wished it had been braver. Fine, not good."),
    ],
    "Lessons in Chemistry": [
        (4.0, "A 1960s chemist forced to host a cooking show and accidentally becoming a feminist icon with her own set of rules, which is a romcom premise doing a lot of work. Garmus writes the two love interests as people rather than categories, and the dog is a genuinely good character. The chemistry-of-the-1950s research is immaculate."),
    ],
    "Tomorrow and Tomorrow and Tomorrow": [
        (4.0, "Two best friends who make video games and then don't speak for twenty-four years, and Zevin writes creative partnership as a kind of marriage with a worse ending. The games-as-art arguments are the best part. The middle drifts into a Bohemia-chic stretch, and Sadie's depression is handled better than the prose around it."),
    ],
    "Exit West": [
        (3.5, "A lovely fable that tips over into something smaller than I wanted."),
    ],
    "A Man Called Ove": [
        (3.5, "Grumpy and kind in roughly equal measure, which is the trick."),
    ],
}

# Comment bodies, written to be usable as replies to any review. Short, opinionated,
# the sort of thing people actually type under someone's review.
COMMENT_POOL = [
    "Okay but nobody talks about the last forty pages. I had to sit there for a minute.",
    "Strong disagree — I found the middle completely inert and the ending doing all the work.",
    "This is the one nobody mentions and it should be in every list of the decade.",
    "I read this in a weekend and then didn't read anything for two weeks.",
    "The prose does something here I still can't explain and I've read it three times.",
    "Honestly the cover is doing more for this book than the text.",
    "People calling this overrated have clearly never read the middle section.",
    "I cried at a bridge scene in this. At a bridge. In a book about a war.",
    "Second this so hard. The ending is not the point and reviews keep pretending it is.",
    "Read it on a recommendation and now I've recommended it to four people.",
    "The world building is doing something really unusual and I don't think it gets enough credit.",
    "I thought about this book for a month after and I still don't like it. Which is annoying.",
    "This is the best thing I've read this year and I've been trying to be hard about it.",
    "The audiobook is worth it even if you have the print, for the pronunciation alone.",
    "I bailed at 200 pages and regret it every single time I see it mentioned.",
    "There's a metaphor in chapter four that I have thought about constantly.",
    "You can tell the author did the research. The details are too specific to be invented.",
    "Fine, you got me, I bought it because of your review. No regrets.",
    "This has been sitting on my shelf unread for a year and now I feel guilty.",
    "The thing that gets me is how quiet it is. Nothing shouts.",
    "Overrated, and I say that as someone who finished it.",
    "Just finished this and immediately started rereading. There is a reason.",
    "The two timelines really do work, which I did not expect.",
    "Everyone should read the last chapter and then decide what they thought about the first.",
    "I don't understand the ending at all and I've read it twice.",
    "Comfort reread, which is a strange thing to want and yet.",
    "This is the third review of this I've seen this month and they're all correct.",
    "Genuinely one of the best endings I've ever read. Genuinely.",
    "It's a five star book that I've been calling a four star book in my head for a year.",
    "The characterisation of the two sisters is worth the cover price alone.",
    "Had to stop reading twice to let it land. Took me a week to pick it back up.",
    "Not for everyone, but if you like the genre this is the top shelf.",
    "The audiobook narrator makes a mediocre book work.",
    "I keep seeing this recommended and I keep not liking it and I think that's just me.",
    "What a book. I'm going to be thinking about the ending at work for days.",
    "My favourite thing about it is how mean it is to people who didn't deserve it.",
    "The first half is a 5, the second half is a 3, and I read both in one sitting.",
    "This is the sort of book that's better without a summary. Don't spoil it for me.",
    "I read this on a train and missed my stop, twice.",
    "It doesn't respect you, it just drags you along with it. That's the charm.",
    "Fascinating book, and I still think the author is being condescending in the third act.",
    "The density put me off for a month and then I got over it and forgave everything.",
    "Just a very good book. Nothing clever, no subtext, just extremely good.",
    "Finished it in two sittings and the second was mostly just sitting in silence with it.",
    "I will be arguing about the ending of this book with people for years.",
    "The idea is genuinely original, which is rarer than a good plot.",
    "This one rewards patience. I gave up at 150 pages and the people who finished it were right.",
    "Every character makes a decision you completely believe. Rare.",
    "It's a slow start and then it absolutely detonates.",
    "Bought it on the strength of one line in someone else's review. No notes.",
    "Not perfect, clearly written by a committee for the middle third, but the first and last are magic.",
]

# (owner, title, description, is_ranked, [(book, note or None), …])
READING_LISTS = [
    (
        "mara_linden",
        "Books That Rearranged Something In My Head",
        "Not necessarily the best books — the ones that left a mark I could feel. Ranked, "
        "badly, in the order they hit me.",
        True,
        [
            ("Beloved", "I had to stop and lie down. Still not sure I have words for it."),
            ("The Left Hand of Darkness", None),
            ("The Dispossessed", None),
            ("Pachinko", None),
            ("The Remains of the Day", "One crack in the facade and it's catastrophic."),
            ("The Name of the Rose", None),
        ],
    ),
    (
        "theo_baptiste",
        "Openers That Don't Foreshadow The End At All",
        "No prologues, no 'this is how it began', no maps. You go in cold and the book "
        "doesn't explain itself for two hundred pages and it works.",
        True,
        [
            ("The Left Hand of Darkness", "Straight into a conversation on a frozen planet."),
            ("Piranesi", None),
            ("Dune", "No cast list, no glossary. Just a planet and a dead duke."),
            ("The Talented Mr Ripley", None),
        ],
    ),
    (
        "naomi_okonkwo",
        "Books I Text People About Immediately After Finishing",
        "Unranked, because the order I finished them in is meaningless. If a book is on "
        "this list you will get a full paragraph from me unprompted.",
        False,
        [
            ("Mexican Gothic", None),
            ("Demon Copperhead", "The driving licence chapter. I cannot be stopped."),
            ("The Book Thief", None),
            ("Wide Sargasso Sea", None),
            ("The Fisherman", "DNFd. Give it a year, apparently it comes back around."),
            ("Klara and the Sun", None),
            ("The Time Traveler's Wife", None),
        ],
    ),
]
# (name, description, owner, members, [(author_username, post_body), …])
GROUPS = [
    (
        "Unreliable Narrators Book Club",
        "Books where the person telling you the story is the problem. Monthly-ish, "
        "slower than that really. We argue about whether an unreliable narrator is a "
        "trick or a subject.",
        "ines_marchetti",
        ["felix_hartmann", "mara_linden", "tamsin_ellery", "rowan_boyle", "naomi_okonkwo"],
        [
            (
                "ines_marchetti",
                "Starting us off with the obvious one: Gone Girl. My argument is that Flynn's "
                "narrator is unreliable in the boring modern sense — she's chosen — but the book "
                "is really about the fact that a marriage is a two-sided unreliability problem. "
                "Read it, then come back and tell me the ending isn't cheap.",
            ),
            (
                "felix_hartmann",
                "I'll argue the opposite: it IS a trick, and a good one. The entire pleasure is "
                "the whiplash in the last fifty pages. If you want to read marriage, read Middlemarch. "
                "This is a machine for making you doubt a narrator, and it works almost too well.",
            ),
            (
                "mara_linden",
                "Third option, please. The Turn of the Screw is the only one on the list where I "
                "genuinely cannot tell whether the ghosts are real, and the governess's letter at "
                "the end is the most unbelievable document in literature — which is either proof "
                "the ghosts are fake or proof she is, and the book refuses to say which.",
            ),
            (
                "tamsin_ellery",
                "Rebecca is the one nobody puts on these lists and it should be on all of them. "
                "The narrator is being gaslit by an entire house. Manderley is the least reliable "
                "character in English fiction and it never speaks in the first person.",
            ),
            (
                "rowan_boyle",
                "For next month, propose Fahrenheit 451. Montag isn't lying — he genuinely doesn't "
                "believe what he saw with his own eyes, which is a different and nastier kind of "
                "unreliable. He's not deceiving us, he's deceiving himself. Discuss.",
            ),
        ],
    ),
    (
        "Hard Sci-Fi & First Contact",
        "Books with the physics left in. No wizards, no psychic swords, no ships that are "
        "really a castle. We read slowly because there's a lot to argue about.",
        "priya_raman",
        ["elin_oseberg", "jonah_whitfield", "theo_baptiste", "mara_linden", "felix_hartmann", "rowan_boyle"],
        [
            (
                "priya_raman",
                "Kicking us off with The Three-Body Problem, since a few of us are on it and a few "
                "of us are pretending to have finished it. I want to talk specifically about the "
                "Red Coast chapters and whether Cixin is actually making an anti-science argument. "
                "I don't think he is. I think he is making an argument about how fast institutions "
                "can turn.",
            ),
            (
                "elin_oseberg",
                "I finished and my answer is: yes, he is, and the sophon passage is where he says so. "
                "Someone stops communication between two planets and nobody in the story asks why we "
                "were told it was a research project. The whole first third is about a bureaucracy "
                "that only lies for seven hundred years.",
            ),
            (
                "jonah_whitfield",
                "Different problem with the book: the Red Coast is a good idea executed about four "
                "times, and by the fifth it stops being a shock and starts being a chapter. Worth it "
                "anyway. The bit nobody mentions is the three-body problem description itself, which "
                "is a genuinely elegant piece of mathematics that Cixin put in a novel and I am still "
                "thinking about.",
            ),
            (
                "theo_baptiste",
                "For the next read let's do Children of Time, and I want us to specifically resist the "
                "obvious reading. The uplift is a metaphor, sure, but Lévi's whole arc is about a "
                "species that invents a faster-than-light social contract and calls it a religion. "
                "That is not a metaphor for anything, that is just physics with politics attached.",
            ),
            (
                "mara_linden",
                "Solaris first, actually. Lem does in a hundred pages what the rest of us take "
                "trilogies for, and I want to argue about the ending, because I think the ending is "
                "the whole book. A scientist confronted with a miracle picks paperwork. That is the "
                "most humane thing in this entire list.",
            ),
            (
                "felix_hartmann",
                "Ancillary Justice for the one after that, and I want to talk about tense. Breq narrates "
                "in the past tense about events she doesn't know she caused for three hundred pages, "
                "which is a formally beautiful way of writing dissociation and I want to know if it "
                "worked for anyone else or if you only notice it at the end.",
            ),
        ],
    ),
]


def _log_dates(rng: random.Random, status: str, anchor: date) -> tuple[date | None, date | None]:
    """Plausible started/finished dates. finished_at only for read/dnf, always
    after started_at, and never in the future."""
    if status == "want_to_read":
        return None, None

    # a read took a fortnight to a month; something you gave up on took less
    span = rng.randint(3, 30) if status == "read" else rng.randint(2, 12)
    # start far enough back that the finish date lands on or before today
    started = anchor - timedelta(days=rng.randint(span + 1, 900))
    if status == "reading":
        return started, None

    return started, started + timedelta(days=span)


def _created_at(rng: random.Random, started: date | None, finished: date | None, now: datetime) -> datetime:
    """When the log was *written up*, as opposed to when the book was read.

    The Feed and the review cards show created_at, and the column defaults to
    now() — so without this every seeded row would carry the timestamp of
    whichever run you happened to do, and the whole feed would read as one
    bulk import rather than months of reading. Tied loosely to the reading
    dates: a log lands a day or three after you finish the book, and a
    want-to-read entry lands a bit before the day you picked it up.
    """
    if finished is not None:
        day, lead = finished, 0
    elif started is not None:
        day, lead = started, rng.randint(1, 20)
    else:
        day, lead = now.date() - timedelta(days=rng.randint(3, 300)), 0

    stamp = datetime.combine(day, time(hour=rng.randint(7, 23), minute=rng.randint(0, 59)), tzinfo=UTC)
    stamp += timedelta(days=lead)
    # A few hours of slack so a book finished this afternoon isn't logged as
    # having been written up "2 minutes ago", but no more — pulling it back
    # further would land before the finish date.
    return min(stamp, now - timedelta(hours=rng.randint(2, 30)))


def _ratings_for(rng: random.Random, count: int) -> list[float]:
    """A believable spread — lots of 4s and 4.5s, a real tail of 3s, and a
    couple of genuine pans. Weighted so the distribution isn't uniform."""
    weights = [(3.0, 0.20), (3.5, 0.20), (4.0, 0.22), (4.5, 0.20), (5.0, 0.08), (2.5, 0.05), (2.0, 0.03), (1.5, 0.02)]
    values = [w for w, _ in weights]
    probs = [p for _, p in weights]
    return [float(rng.choices(values, weights=probs, k=1)[0]) for _ in range(count)]


def _avatar_url(username: str) -> str:
    # DiceBear's hosted API, no key needed: an illustrated portrait seeded
    # by username, so it's the same picture on every run rather than a new
    # random face each time. Background tinted to match --parchment so it
    # doesn't sit inside the app as a plain white square.
    return f"https://api.dicebear.com/9.x/notionists/svg?seed={username}&backgroundColor=f1e9d8"


async def seed_readers(db) -> dict[str, models.User]:
    """The ten fake accounts, keyed by username for the rest of the script."""
    result = await db.execute(select(models.User))
    existing = {u.username.lower(): u for u in result.scalars().all()}

    created = given_avatar = 0
    for username, email in READERS:
        if username in existing:
            # Backfills anyone created before avatars existed here, so a
            # re-run repairs old rows instead of only handling new ones.
            user = existing[username]
            if not user.avatar_url:
                user.avatar_url = _avatar_url(username)
                given_avatar += 1
            continue
        user = models.User(
            username=username,
            email=email,
            password_hash=hash_password(DEMO_PASSWORD),
            avatar_url=_avatar_url(username),
        )
        db.add(user)
        existing[username] = user
        created += 1

    await db.commit()
    print(f"  {created} created, {given_avatar} given an avatar, "
          f"{len(READERS) - created - given_avatar} already present")
    return existing


async def seed_follows(db, readers: dict[str, models.User]) -> None:
    rng = random.Random(20260928)
    result = await db.execute(select(models.Follow))
    have = {(f.follower_id, f.followed_id) for f in result.scalars().all()}

    wanted = set()
    for follower, followed in FOLLOW_EDGES:
        wanted.add((follower, followed))

    # Top up anyone with fewer than 3 outgoing so no feed is empty. Iterate
    # READERS, not the readers dict, so the pick is the same on every run.
    for username, _ in READERS:
        if username not in readers:
            continue
        mine = [w for w in wanted if w[0] == username]
        if len(mine) >= 3:
            continue
        candidates = [u for u, _ in READERS if u != username and (username, u) not in wanted]
        rng.shuffle(candidates)
        wanted.update((username, c) for c in candidates[: 3 - len(mine)])

    created = 0
    for follower, followed in sorted(wanted):
        if follower not in readers or followed not in readers:
            continue
        key = (readers[follower].id, readers[followed].id)
        if key in have or key[0] == key[1]:
            continue
        db.add(models.Follow(follower_id=key[0], followed_id=key[1]))
        have.add(key)
        created += 1

    await db.commit()
    print(f"  {created} created, {len(have) - created} already present")


async def seed_logs(db, readers: dict[str, models.User]) -> dict[str, list[models.ReadingLog]]:
    """The bulk of it: a few hundred logs across 124 books, with reviews."""
    rng = random.Random(7654321)
    anchor = date.today()
    now = datetime.now(UTC)

    result = await db.execute(select(models.Book))
    books = {b.title: b for b in result.scalars().all()}

    result = await db.execute(select(models.ReadingLog.user_id, models.ReadingLog.book_id))
    have = {(uid, bid) for uid, bid in result.all()}

    statuses = ["read"] * 46 + ["want_to_read"] * 22 + ["reading"] * 18 + ["dnf"] * 14
    # Sample from READERS in declaration order, not from the readers dict, whose
    # iteration order comes out of the database and can differ between runs.
    # The choice of who logs what has to be a pure function of the seed or the
    # dedupe below never converges.
    names = [u for u, _ in READERS if u in readers]
    by_title: dict[str, list[models.ReadingLog]] = {}
    made: list[models.ReadingLog] = []
    created = skipped = 0

    for genre, titles in LOGGED_BOOKS.items():
        for title in titles:
            book = books.get(title)
            if book is None:
                print(f"  ! {title} is not in the catalogue, skipping")
                continue

            reviews = REVIEWS.get(title, [])
            hot = title in HOT_BOOKS

            # Hot books always get three logs so Popular Reviews has a top
            # three; everything else gets one to three.
            n = 3 if hot else rng.choice([1, 1, 1, 2, 2, 3])
            authors = rng.sample(names, n)

            for i, username in enumerate(authors):
                # Every random draw happens before the "already there?" check on
                # purpose. Skipping earlier would consume fewer values on a
                # re-run than on a first run, which desynchronises the stream
                # and makes the next run pick different readers — and so append
                # a second log for a book someone already logged.
                review = reviews[i] if i < len(reviews) else None
                status = rng.choice(statuses)

                # A review is a thing you write after finishing, so a log with
                # prose on it is always read or dnf — never want_to_read.
                if review is not None:
                    status = "read" if review[0] >= 3.0 else "dnf"

                started, finished = _log_dates(rng, status, anchor)
                rated = status in ("read", "dnf")
                if review is not None and rated:
                    rating = review[0]
                elif rated:
                    rating = _ratings_for(rng, 1)[0]
                else:
                    rating = None
                is_reread = rng.random() < 0.06
                created_at = _created_at(rng, started, finished, now)

                if (readers[username].id, book.id) in have:
                    skipped += 1
                    continue

                log = models.ReadingLog(
                    user_id=readers[username].id,
                    book_id=book.id,
                    status=status,
                    rating=rating,
                    review_text=review[1] if review else None,
                    started_at=started,
                    finished_at=finished,
                    is_reread=is_reread,
                    created_at=created_at,
                )
                db.add(log)
                have.add((readers[username].id, book.id))
                made.append(log)
                by_title.setdefault(title, []).append(log)
                created += 1

        # per-genre batches keeps the transaction sizes sane
        await db.commit()

    # commits expire every object, so pull the rows back explicitly — a bare
    # attribute read afterwards would try to hit the db outside a greenlet.
    for log in made:
        await db.refresh(log)
    print(f"  {created} created, {skipped} already present")
    return by_title


async def seed_comments(db, readers: dict[str, models.User], logs: list[models.ReadingLog]) -> None:
    """1-3 comments on ~35 of the reviewed logs, a few threaded via parent_id."""
    rng = random.Random(112233)
    now = datetime.now(UTC)
    commenter_ids = [readers[u].id for u, _ in READERS]

    result = await db.execute(select(models.Comment.log_id, models.Comment.body))
    have = {(log_id, body) for log_id, body in result.all()}

    reviewed = [log for log in logs if log.review_text]
    rng.shuffle(reviewed)
    targets = reviewed[:35]

    created = 0
    replies = 0
    for log in targets:
        # Commenters are always somebody other than the log's author.
        others = [uid for uid in commenter_ids if uid != log.user_id]
        rng.shuffle(others)
        n = rng.randint(1, 3)
        parent = None
        for _ in range(n):
            # both draws happen before the skip check so the rng stream stays
            # aligned across runs, whether or not the row is already there
            roll = rng.random()
            is_reply = parent is not None and roll < 0.35
            pool = [b for b in COMMENT_POOL if parent is None or b != parent.body]
            body = rng.choice(pool)
            author = others.pop() if others else None

            if author is None or (log.id, body) in have:
                continue

            comment = models.Comment(
                user_id=author,
                log_id=log.id,
                body=body,
                parent_id=parent.id if is_reply else None,
                # a reply is always after the thing it replies to
                created_at=(parent.created_at if is_reply else log.created_at)
                + timedelta(hours=rng.randint(1, 40)),
            )
            db.add(comment)
            await db.flush()  # need the id to point a reply at it
            if is_reply:
                replies += 1
            have.add((log.id, body))
            parent = comment
            created += 1

    await db.commit()
    print(f"  {created} created ({replies} threaded replies), "
          f"{len(have) - created} already present")


async def seed_likes(db, readers: dict[str, models.User], by_title: dict[str, list[models.ReadingLog]]) -> None:
    """Likes, weighted towards long opinionated reviews, with the hot books'
    top-3 given fixed counts so the Popular Reviews ranking is unambiguous."""
    rng = random.Random(445566)
    now = datetime.now(UTC)

    result = await db.execute(select(models.Like.user_id, models.Like.log_id))
    have = {(uid, lid) for uid, lid in result.all()}

    reader_ids = [readers[u].id for u, _ in READERS]

    created = 0
    for title, all_logs in by_title.items():
        group = [log for log in all_logs if log.review_text]
        if not group:
            continue

        # rank the book's reviewed logs: most-liked first
        if title in HOT_BOOKS and len(group) == 3:
            order = sorted(group, key=lambda lg: (lg.rating or 0, len(lg.review_text or "")), reverse=True)
            # deliberately uneven so the ranking is a real ranking
            targets = [(order[0], 8), (order[1], 5), (order[2], 3)]
        else:
            targets = []
            for log in all_logs:
                if not log.review_text:
                    # someone still liked the log, just not as often
                    if rng.random() < 0.22:
                        targets.append((log, rng.randint(1, 2)))
                    continue
                # longer + better rated = more likely to be liked
                weight = min(6.0, 1.0 + len(log.review_text) / 220 + max(0.0, (log.rating or 0) - 3.0))
                count = rng.choices([0, 1, 2, 3, 4, 5], weights=[0.2, 0.2, 0.2, 0.18, 0.14, 0.08])[0]
                if rng.random() < weight / 7:
                    targets.append((log, count))

        for log, count in targets:
            likers = [uid for uid in reader_ids if uid != log.user_id]
            rng.shuffle(likers)
            for uid in likers[:count]:
                key = (uid, log.id)
                if key in have:
                    continue
                db.add(models.Like(
                    user_id=uid,
                    log_id=log.id,
                    # a like always follows the review it is on
                    created_at=log.created_at + timedelta(hours=rng.randint(1, 60)),
                ))
                have.add(key)
                created += 1

    await db.commit()
    print(f"  {created} created, {len(have) - created} already present")


async def seed_lists(db, readers: dict[str, models.User]) -> None:
    rng = random.Random(778899)
    now = datetime.now(UTC)
    result = await db.execute(select(models.Book))
    books = {b.title: b for b in result.scalars().all()}

    result = await db.execute(select(models.ReadingList.user_id, models.ReadingList.title))
    have = {(uid, t) for uid, t in result.all()}

    result = await db.execute(select(models.ListItem.list_id, models.ListItem.book_id))
    have_items = set(result.all())

    created = skipped = 0
    for owner, title, description, is_ranked, items in READING_LISTS:
        if owner not in readers:
            continue
        key = (readers[owner].id, title)
        if key in have:
            skipped += 1
            continue

        reading_list = models.ReadingList(
            user_id=readers[owner].id,
            title=title,
            description=description,
            is_ranked=is_ranked,
            created_at=now - timedelta(days=rng.randint(20, 75)),
        )
        db.add(reading_list)
        await db.flush()

        for position, (book_title, note) in enumerate(items, start=1):
            book = books.get(book_title)
            if book is None:
                continue
            item_key = (reading_list.id, book.id)
            if item_key in have_items:
                continue
            db.add(models.ListItem(
                list_id=reading_list.id,
                book_id=book.id,
                position=position,
                note=note,
            ))
            have_items.add(item_key)

        have.add(key)
        created += 1
        print(f"  + {title} ({len(items)} books, {'ranked' if is_ranked else 'unranked'})")

    await db.commit()
    print(f"  {created} created, {skipped} already present")


async def seed_groups(db, readers: dict[str, models.User]) -> None:
    rng = random.Random(334455)
    now = datetime.now(UTC)
    result = await db.execute(select(models.Group.owner_id, models.Group.name))
    have = {(oid, n) for oid, n in result.all()}

    result = await db.execute(select(models.GroupMember.group_id, models.GroupMember.user_id))
    have_members = set(result.all())

    created = skipped = 0
    for name, description, owner, members, posts in GROUPS:
        if owner not in readers:
            continue
        key = (readers[owner].id, name)
        if key in have:
            skipped += 1
            continue

        # the club has been running for a couple of months
        founded = now - timedelta(days=rng.randint(55, 80))

        group = models.Group(
            name=name,
            description=description,
            owner_id=readers[owner].id,
            created_at=founded,
        )
        db.add(group)
        await db.flush()

        # owner gets their own member row with role="owner", same as
        # POST /api/groups does in routers/groups.py
        db.add(models.GroupMember(
            group_id=group.id,
            user_id=readers[owner].id,
            role="owner",
            joined_at=founded,
        ))

        for member in members:
            if member not in readers:
                continue
            mkey = (group.id, readers[member].id)
            if mkey in have_members:
                continue
            db.add(models.GroupMember(
                group_id=group.id,
                user_id=readers[member].id,
                role="member",
                joined_at=founded + timedelta(days=rng.randint(1, 21)),
            ))
            have_members.add(mkey)

        # posts march forward in time, the way a thread actually grows
        when = founded + timedelta(days=rng.randint(3, 12))
        for author, body in posts:
            if author not in readers:
                continue
            db.add(models.Post(
                group_id=group.id,
                user_id=readers[author].id,
                body=body,
                created_at=when,
            ))
            when += timedelta(days=rng.randint(1, 9), hours=rng.randint(1, 20))

        have.add(key)
        created += 1
        print(f"  + {name} ({len(members) + 1} members, {len(posts)} posts)")

    await db.commit()
    print(f"  {created} created, {skipped} already present")


async def report(db) -> None:
    print("\ntotals:")
    for model, label in [
        (models.User, "users"),
        (models.Follow, "follows"),
        (models.ReadingLog, "reading_logs"),
        (models.Comment, "comments"),
        (models.Like, "likes"),
        (models.ReadingList, "lists"),
        (models.ListItem, "list_items"),
        (models.Group, "groups"),
        (models.GroupMember, "group_members"),
        (models.Post, "posts"),
        (models.Message, "messages"),
        (models.AudioSession, "audio_sessions"),
    ]:
        n = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        print(f"  {label:14} {n}")


async def seed():
    async with SessionLocal() as db:
        print("seeding reader accounts…")
        readers = await seed_readers(db)

        print("seeding follows…")
        await seed_follows(db, readers)

        print("seeding reading logs…")
        by_title = await seed_logs(db, readers)
        made = [log for group in by_title.values() for log in group]

        print("seeding comments…")
        await seed_comments(db, readers, made)

        print("seeding likes…")
        await seed_likes(db, readers, by_title)

        print("seeding reading lists…")
        await seed_lists(db, readers)

        print("seeding groups…")
        await seed_groups(db, readers)

        await report(db)

        print(f"\nsign in as any of the seeded readers with the password {DEMO_PASSWORD!r}")


if __name__ == "__main__":
    asyncio.run(seed())
