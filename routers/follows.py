from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
from auth import get_current_user
from database import get_db
from schemas import UserPublic

router = APIRouter()


@router.post("/{user_id}/follow", status_code=status.HTTP_201_CREATED)
async def follow_user(
    user_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot follow yourself")

    result = await db.execute(select(models.User).where(models.User.id == user_id))
    target_user = result.scalars().first()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = await db.execute(
        select(models.Follow).where(
            models.Follow.follower_id == current_user.id,
            models.Follow.followed_id == user_id,
        ),
    )
    existing_follow = result.scalars().first()
    if existing_follow:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already following this user")

    new_follow = models.Follow(follower_id=current_user.id, followed_id=user_id)
    db.add(new_follow)
    await db.commit()
    return {"message": "Followed"}


@router.delete("/{user_id}/follow")
async def unfollow_user(
    user_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.Follow).where(
            models.Follow.follower_id == current_user.id,
            models.Follow.followed_id == user_id,
        ),
    )
    follow = result.scalars().first()
    if not follow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not following this user")

    await db.delete(follow)
    await db.commit()
    return {"message": "Unfollowed"}


# Get followers
@router.get("/{user_id}/followers", response_model=list[UserPublic])
async def get_followers(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
    offset: int = 0,
):
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = await db.execute(
        select(models.User)
        .join(models.Follow, models.Follow.follower_id == models.User.id)
        .where(models.Follow.followed_id == user_id)
        .limit(limit)
        .offset(offset),
    )
    return result.scalars().all()


# Get following
@router.get("/{user_id}/following", response_model=list[UserPublic])
async def get_following(
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
    offset: int = 0,
):
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = await db.execute(
        select(models.User)
        .join(models.Follow, models.Follow.followed_id == models.User.id)
        .where(models.Follow.follower_id == user_id)
        .limit(limit)
        .offset(offset),
    )
    return result.scalars().all()
