from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from auth import get_current_user
from database import get_db
from permissions import check_ownership
from schemas import CommentResponse, CommentUpdate

router = APIRouter()


@router.get("/{comment_id}", response_model=CommentResponse)
async def get_comment(comment_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Comment).options(selectinload(models.Comment.author)).where(models.Comment.id == comment_id),
    )
    comment = result.scalars().first()

    if comment:
        return comment

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")


@router.patch("/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: int,
    comment_data: CommentUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(models.Comment).options(selectinload(models.Comment.author)).where(models.Comment.id == comment_id),
    )
    comment = result.scalars().first()

    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    check_ownership(comment.user_id, current_user, "Not authorized to update this comment")

    comment.body = comment_data.body

    await db.commit()
    await db.refresh(comment)
    return comment


@router.delete("/{comment_id}")
async def delete_comment(
    comment_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Comment).where(models.Comment.id == comment_id))
    comment = result.scalars().first()

    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    check_ownership(comment.user_id, current_user, "Not authorized to delete this comment")

    await db.delete(comment)
    await db.commit()
    return {"message": "Comment deleted successfully"}
