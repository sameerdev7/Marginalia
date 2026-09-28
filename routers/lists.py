from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from auth import get_current_user
from database import get_db
from permissions import check_ownership
from schemas import (
    ReadingListResponse,
    ReadingListCreate,
    ReadingListUpdate,
    ListItemResponse,
    ListItemCreate,
    ListItemUpdate,
)

router = APIRouter()


@router.get("", response_model=list[ReadingListResponse])
async def get_lists(
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
):
    query = select(models.ReadingList)
    if user_id is not None:
        query = query.where(models.ReadingList.user_id == user_id)
    query = query.order_by(models.ReadingList.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{list_id}", response_model=ReadingListResponse)
async def get_list(list_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.ReadingList).where(models.ReadingList.id == list_id))
    reading_list = result.scalars().first()

    if reading_list:
        return reading_list

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List not found")


@router.post("", response_model=ReadingListResponse, status_code=status.HTTP_201_CREATED)
async def create_list(
    reading_list: ReadingListCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    new_list = models.ReadingList(
        user_id=current_user.id,
        title=reading_list.title,
        description=reading_list.description,
        is_ranked=reading_list.is_ranked,
    )
    db.add(new_list)
    await db.commit()
    await db.refresh(new_list)

    return new_list


@router.patch("/{list_id}", response_model=ReadingListResponse)
async def update_list(
    list_id: int,
    list_data: ReadingListUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingList).where(models.ReadingList.id == list_id))
    reading_list = result.scalars().first()

    if not reading_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List not found")

    check_ownership(reading_list.user_id, current_user, "Not authorized to update this list")

    update_data = list_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(reading_list, field, value)

    await db.commit()
    await db.refresh(reading_list)
    return reading_list


@router.delete("/{list_id}")
async def delete_list(
    list_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingList).where(models.ReadingList.id == list_id))
    reading_list = result.scalars().first()

    if not reading_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List not found")

    check_ownership(reading_list.user_id, current_user, "Not authorized to delete this list")

    await db.delete(reading_list)
    await db.commit()
    return {"message": "List deleted successfully"}


# Items on a list
@router.get("/{list_id}/items", response_model=list[ListItemResponse])
async def get_list_items(list_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.ListItem)
        .options(selectinload(models.ListItem.book).selectinload(models.Book.owner))
        .where(models.ListItem.list_id == list_id)
        .order_by(models.ListItem.position),
    )
    return result.scalars().all()


@router.post("/{list_id}/items", response_model=ListItemResponse, status_code=status.HTTP_201_CREATED)
async def add_list_item(
    list_id: int,
    item: ListItemCreate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingList).where(models.ReadingList.id == list_id))
    reading_list = result.scalars().first()
    if not reading_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List not found")

    check_ownership(reading_list.user_id, current_user, "Not authorized to add items to this list")

    result = await db.execute(select(models.Book).where(models.Book.id == item.book_id))
    if not result.scalars().first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    result = await db.execute(
        select(models.ListItem).where(
            models.ListItem.list_id == list_id,
            models.ListItem.book_id == item.book_id,
        ),
    )
    existing_item = result.scalars().first()
    if existing_item:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Book already on this list")

    new_item = models.ListItem(
        list_id=list_id,
        book_id=item.book_id,
        position=item.position,
        note=item.note,
    )
    db.add(new_item)
    await db.commit()

    # Re-read rather than `db.refresh`: ListItemResponse nests book, which in
    # turn nests the book's owner. Refreshing only "book" leaves book.owner
    # unloaded, and the serializer's lazy load of it happens outside the async
    # greenlet -> MissingGreenlet -> 500. Same selectinload the GET uses.
    result = await db.execute(
        select(models.ListItem)
        .options(selectinload(models.ListItem.book).selectinload(models.Book.owner))
        .where(models.ListItem.id == new_item.id),
    )
    return result.scalars().first()


@router.patch("/{list_id}/items/{item_id}", response_model=ListItemResponse)
async def update_list_item(
    list_id: int,
    item_id: int,
    item_data: ListItemUpdate,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingList).where(models.ReadingList.id == list_id))
    reading_list = result.scalars().first()
    if not reading_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List not found")

    check_ownership(reading_list.user_id, current_user, "Not authorized to update items on this list")

    result = await db.execute(
        select(models.ListItem)
        .options(selectinload(models.ListItem.book).selectinload(models.Book.owner))
        .where(models.ListItem.id == item_id, models.ListItem.list_id == list_id),
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List item not found")

    update_data = item_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)

    await db.commit()

    # Same reasoning as add_list_item: a bare refresh() would expire the
    # preloaded book/book.owner, so re-read them instead of lazy-loading.
    result = await db.execute(
        select(models.ListItem)
        .options(selectinload(models.ListItem.book).selectinload(models.Book.owner))
        .where(models.ListItem.id == item_id, models.ListItem.list_id == list_id),
    )
    return result.scalars().first()


@router.delete("/{list_id}/items/{item_id}")
async def delete_list_item(
    list_id: int,
    item_id: int,
    current_user: Annotated[models.User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.ReadingList).where(models.ReadingList.id == list_id))
    reading_list = result.scalars().first()
    if not reading_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List not found")

    check_ownership(reading_list.user_id, current_user, "Not authorized to remove items from this list")

    result = await db.execute(
        select(models.ListItem).where(models.ListItem.id == item_id, models.ListItem.list_id == list_id),
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="List item not found")

    await db.delete(item)
    await db.commit()
    return {"message": "List item removed successfully"}
