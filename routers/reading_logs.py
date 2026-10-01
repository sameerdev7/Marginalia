from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from auth import get_current_user
from database import get_db
from permissions import check_ownership
from schemas import (
    FriendsPopularItem,
    ReadingLogResponse,
    ReadingLogCreate,
    ReadingLogUpdate,
    CommentResponse,
    CommentCreate,
    UserPublic,
)

router = APIRouter()


# feed has to come before /{log_id} or FastAPI tries to parse "feed" as a log id
@router.get("/feed", response_model=list[ReadingLogResponse])
async def get_feed(
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
    offset: int = 0,
):
    result = await db.execute(
        select(models.ReadingLog)
        .join(models.Follow, models.Follow.followed_id == models.ReadingLog.user_id)
        .where(models.Follow.follower_id == current_user.id)
        .order_by(models.ReadingLog.created_at.desc())
        .limit(limit)
        .offset(offset),
    )
    return result.scalars().all()


# Also before /{log_id}.
@router.get("/friends/popular", response_model=list[FriendsPopularItem])
async def popular_among_friends(
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 90,
    limit: int = 12,
):
    """Books the people you follow logged recently, most-logged first.

    Counts distinct readers per book (someone logging a book twice is still one
    reader). Ties break toward the book logged most recently.
    """
    since = datetime.now(UTC) - timedelta(days=min(max(days, 1), 3650))
    result = await db.execute(
        select(models.ReadingLog)
        .join(models.Follow, models.Follow.followed_id == models.ReadingLog.user_id)
        .where(
            models.Follow.follower_id == current_user.id,
            models.ReadingLog.created_at >= since,
        )
        .options(
            selectinload(models.ReadingLog.user),
            # BookResponse nests the owner, so it must be loaded too.
            selectinload(models.ReadingLog.book).selectinload(models.Book.owner),
        )
        .order_by(models.ReadingLog.created_at.desc())
    )

    books: dict[int, dict] = {}
    for log in result.scalars():
        entry = books.setdefault(
            log.book_id, {"book": log.book, "friends": {}, "latest": log.created_at}
        )
        entry["friends"].setdefault(log.user_id, log.user)

    ranked = sorted(
        books.values(), key=lambda e: (len(e["friends"]), e["latest"]), reverse=True
    )[: min(limit, 50)]
    return [
        {"book": e["book"], "readers": len(e["friends"]), "friends": list(e["friends"].values())[:4]}
        for e in ranked
    ]


@router.get("", response_model=list[ReadingLogResponse])
async def get_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: int | None = None,
    book_id: int | None = None,
    has_review: bool | None = None,
    sort: str = "recent",
    limit: int = 20,
    offset: int = 0,
):
    query = select(models.ReadingLog)

    if user_id is not None:
        query = query.where(models.ReadingLog.user_id == user_id)

    if book_id is not None:
        query = query.where(models.ReadingLog.book_id == book_id)

    if has_review is True:
        query = query.where(models.ReadingLog.review_text.is_not(None))
    elif has_review is False:
        query = query.where(models.ReadingLog.review_text.is_(None))

    if sort == "popular":
        like_count = func.count(models.Like.id)
        query = (
            query.outerjoin(models.Like, models.Like.log_id == models.ReadingLog.id)
            .group_by(models.ReadingLog.id)
            .order_by(like_count.desc())
        )
    else:
        query = query.order_by(models.ReadingLog.created_at.desc())

    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{log_id}", response_model=ReadingLogResponse)
async def get_log(log_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.ReadingLog).where(models.ReadingLog.id == log_id))
    log = result.scalars().first()

    if log:
        return log

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reading log not found")


@router.post("", response_model=ReadingLogResponse, status_code=status.HTTP_201_CREATED)
async def create_log(
    log: ReadingLogCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Book).where(models.Book.id == log.book_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    new_log = models.ReadingLog(
        user_id=current_user.id,
        book_id=log.book_id,
        status=log.status,
        rating=log.rating,
        review_text=log.review_text,
        started_at=log.started_at,
        finished_at=log.finished_at,
        is_reread=log.is_reread,
    )
    db.add(new_log)
    await db.commit()
    await db.refresh(new_log)

    return new_log


@router.patch("/{log_id}", response_model=ReadingLogResponse)
async def update_log(
    log_id: int,
    log_data: ReadingLogUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingLog).where(models.ReadingLog.id == log_id))
    log = result.scalars().first()

    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reading log not found")

    check_ownership(log.user_id, current_user, "Not authorized to update this reading log")

    update_data = log_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(log, field, value)

    await db.commit()
    await db.refresh(log)
    return log


@router.delete("/{log_id}")
async def delete_log(
    log_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingLog).where(models.ReadingLog.id == log_id))
    log = result.scalars().first()

    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reading log not found")

    check_ownership(log.user_id, current_user, "Not authorized to delete this reading log")

    await db.delete(log)
    await db.commit()
    return {"message": "Reading log deleted successfully"}


# Comments on a log
@router.get("/{log_id}/comments", response_model=list[CommentResponse])
async def get_comments(log_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Comment)
        .options(selectinload(models.Comment.author))
        .where(models.Comment.log_id == log_id)
        .order_by(models.Comment.created_at),
    )
    return result.scalars().all()


@router.post("/{log_id}/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(
    log_id: int,
    comment: CommentCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingLog).where(models.ReadingLog.id == log_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reading log not found")

    if comment.parent_id is not None:
        result = await db.execute(select(models.Comment).where(models.Comment.id == comment.parent_id))
        parent = result.scalars().first()
        if not parent or parent.log_id != log_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent comment not found on this log")

    new_comment = models.Comment(
        user_id=current_user.id,
        log_id=log_id,
        body=comment.body,
        parent_id=comment.parent_id,
        author=current_user,
    )
    db.add(new_comment)
    await db.commit()
    await db.refresh(new_comment)

    return new_comment


# Likes on a log
@router.post("/{log_id}/like", status_code=status.HTTP_201_CREATED)
async def like_log(
    log_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingLog).where(models.ReadingLog.id == log_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reading log not found")

    result = await db.execute(
        select(models.Like).where(models.Like.user_id == current_user.id, models.Like.log_id == log_id),
    )
    existing_like = result.scalars().first()
    if existing_like:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already liked this reading log")

    new_like = models.Like(user_id=current_user.id, log_id=log_id)
    db.add(new_like)
    await db.commit()
    return {"message": "Liked"}


@router.delete("/{log_id}/like")
async def unlike_log(
    log_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.Like).where(models.Like.user_id == current_user.id, models.Like.log_id == log_id),
    )
    like = result.scalars().first()
    if not like:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reading log not liked")

    await db.delete(like)
    await db.commit()
    return {"message": "Unliked"}


@router.get("/{log_id}/likes", response_model=list[UserPublic])
async def get_likes(log_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User)
        .join(models.Like, models.Like.user_id == models.User.id)
        .where(models.Like.log_id == log_id),
    )
    return result.scalars().all()
