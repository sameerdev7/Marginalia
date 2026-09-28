"""Content-based "similar books" via TF-IDF + cosine similarity.

Each book becomes one document (genre + author + description), TF-IDF turns
those documents into vectors, and cosine similarity ranks every other book
against the one being viewed. Genre and author are repeated in the document
so they carry more weight than one-off words buried in a long description —
otherwise two books sharing a genre barely move the score against two books
that just happen to share more descriptive vocabulary.

Fit fresh on every call rather than cached: the catalogue is small enough
(a few hundred books) that refitting is well under the endpoint's response
budget, and it means a new or edited book shows up in other books' results
immediately, with nothing to invalidate.
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import models


def _document(book: models.Book) -> str:
    return f"{book.genre} {book.genre} {book.genre} {book.author} {book.author} {book.description}"


def similar_books(
    target: models.Book,
    catalogue: list[models.Book],
    limit: int = 6,
) -> list[tuple[models.Book, float]]:
    others = [book for book in catalogue if book.id != target.id]
    if not others:
        return []

    documents = [_document(target)] + [_document(book) for book in others]
    matrix = TfidfVectorizer(stop_words="english").fit_transform(documents)
    scores = cosine_similarity(matrix[0:1], matrix[1:])[0]

    ranked = sorted(zip(others, scores), key=lambda pair: pair[1], reverse=True)
    return [(book, float(score)) for book, score in ranked[:limit] if score > 0]
