from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from auth import get_current_user, oauth2_scheme_optional, verify_access_token
from database import get_db
from permissions import check_ownership
from schemas import JournalCreate, JournalResponse, JournalSummary, JournalUpdate

router = APIRouter()

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")


async def _require_book(db: AsyncSession, book_id: int | None) -> None:
    if book_id is not None and await db.get(models.Book, book_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")


@router.get("", response_model=list[JournalSummary])
async def list_entries(
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: int | None = None,
    book_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
):
    """Published entries, newest first. Public."""
    query = select(models.JournalEntry).where(models.JournalEntry.published.is_(True))
    if user_id is not None:
        query = query.where(models.JournalEntry.user_id == user_id)
    if book_id is not None:
        query = query.where(models.JournalEntry.book_id == book_id)
    query = (
        query.order_by(models.JournalEntry.published_at.desc())
        .limit(min(limit, 50))
        .offset(offset)
    )
    return (await db.execute(query)).scalars().all()


# Declared before "/{entry_id}" so "mine" isn't parsed as an id.
@router.get("/mine", response_model=list[JournalSummary])
async def my_entries(
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """The caller's own entries — drafts included — most recently edited first."""
    result = await db.execute(
        select(models.JournalEntry)
        .where(models.JournalEntry.user_id == current_user.id)
        .order_by(models.JournalEntry.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/{entry_id}", response_model=JournalResponse)
async def get_entry(
    entry_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
):
    entry = await db.get(models.JournalEntry, entry_id)
    if entry is None:
        raise NOT_FOUND
    if not entry.published:
        # Drafts are private: to anyone but the author they simply don't exist.
        viewer = verify_access_token(token) if token else None
        if viewer is None or int(viewer) != entry.user_id:
            raise NOT_FOUND
    return entry


@router.post("", response_model=JournalResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    payload: JournalCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await _require_book(db, payload.book_id)
    entry = models.JournalEntry(
        user_id=current_user.id,
        title=payload.title.strip(),
        subtitle=(payload.subtitle or "").strip() or None,
        body=payload.body,
        cover_url=(payload.cover_url or "").strip() or None,
        book_id=payload.book_id,
        published=payload.published,
        published_at=datetime.now(UTC) if payload.published else None,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=JournalResponse)
async def update_entry(
    entry_id: int,
    payload: JournalUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    entry = await db.get(models.JournalEntry, entry_id)
    if entry is None:
        raise NOT_FOUND
    check_ownership(entry.user_id, current_user, "Not authorized to edit this entry")

    data = payload.model_dump(exclude_unset=True)
    if "book_id" in data:
        await _require_book(db, data["book_id"])
    for field in ("subtitle", "cover_url"):
        if field in data:
            data[field] = (data[field] or "").strip() or None
    if data.get("title"):
        data["title"] = data["title"].strip()
    if data.get("published") is None:
        data.pop("published", None)

    for field, value in data.items():
        setattr(entry, field, value)
    # First publication stamps the date; unpublishing keeps it so a re-publish
    # doesn't jump the entry to the top of the list.
    if entry.published and entry.published_at is None:
        entry.published_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    entry = await db.get(models.JournalEntry, entry_id)
    if entry is None:
        raise NOT_FOUND
    check_ownership(entry.user_id, current_user, "Not authorized to delete this entry")
    await db.delete(entry)
    await db.commit()
