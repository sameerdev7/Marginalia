from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from auth import get_current_user
from database import get_db
from permissions import check_ownership
from recommendations import similar_books
from schemas import BookResponse, BookCreate, BookUpdate, ExternalBookResult, SimilarBookResponse

router = APIRouter()


# has to come before /{book_id} or FastAPI tries to parse "search-external" as a book id
@router.get("/search-external", response_model=list[ExternalBookResult])
async def search_external_books(q: str):
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                "https://openlibrary.org/search.json",
                params={"q": q, "limit": 10},
            )
        response.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not reach Open Library")

    results = []
    for doc in response.json().get("docs", [])[:10]:
        cover_id = doc.get("cover_i")
        results.append(
            ExternalBookResult(
                title=doc.get("title", ""),
                author=(doc.get("author_name") or [None])[0],
                year=doc.get("first_publish_year"),
                cover_url=f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None,
                pages=doc.get("number_of_pages_median"),
            ),
        )
    return results


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Book).options(selectinload(models.Book.owner)).where(models.Book.id == book_id),
    )
    book = result.scalars().first()
    
    if book:
        return book

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")


@router.get("/{book_id}/similar", response_model=list[SimilarBookResponse])
async def get_similar_books(
    book_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 6,
):
    result = await db.execute(select(models.Book).where(models.Book.id == book_id))
    book = result.scalars().first()

    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")

    catalogue = await db.execute(select(models.Book).options(selectinload(models.Book.owner)))
    ranked = similar_books(book, catalogue.scalars().all(), limit=limit)

    return [
        SimilarBookResponse(**BookResponse.model_validate(match).model_dump(), similarity=round(score, 3))
        for match, score in ranked
    ]

@router.post("", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
async def create_book(
    book: BookCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    new_book = models.Book(
        title = book.title,
        author = book.author,
        genre = book.genre,
        year = book.year,
        cover_url = book.cover_url,
        pages = book.pages,
        description = book.description,
        user_id = current_user.id,
        owner = current_user,
    )
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)

    return new_book

@router.put("/{book_id}", response_model=BookResponse)
async def update_book(
    book_id: int,
    book: BookCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.Book).options(selectinload(models.Book.owner)).where(models.Book.id == book_id)
    )

    existing_book = result.scalars().first()

    if not existing_book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    check_ownership(existing_book.user_id, current_user, "Not authorized to update this book")

    existing_book.title = book.title
    existing_book.author = book.author
    existing_book.genre = book.genre
    existing_book.year = book.year
    existing_book.cover_url = book.cover_url
    existing_book.pages = book.pages
    existing_book.description = book.description
    
    await db.commit()
    await db.refresh(existing_book)
    
    return existing_book

@router.patch("/{book_id}", response_model=BookResponse)
async def update_book_partial(
    book_id: int,
    book_data: BookUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Book).options(selectinload(models.Book.owner)).where(models.Book.id == book_id))
    book = result.scalars().first()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )

    check_ownership(book.user_id, current_user, "Not authorized to update this book")

    update_data = book_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(book, field, value)
        
    await db.commit()
    await db.refresh(book)
    return book


@router.delete("/{book_id}")
async def delete_book(
    book_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.Book).where(models.Book.id == book_id)
    )

    book = result.scalars().first()

    if not book:
        raise HTTPException(status_code = status.HTTP_404_NOT_FOUND, detail="Book not found")

    check_ownership(book.user_id, current_user, "Not authorized to delete this book")

    await db.delete(book)
    await db.commit()
    return {"message": "Book deleted succesfully"}
