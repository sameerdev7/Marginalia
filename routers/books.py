from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select 
from sqlalchemy.ext.asyncio import AsyncSession

import models
from database import get_db 
from schemas import BookResponse, BookCreate, BookUpdate

router = APIRouter()



@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Book).where(models.Book.id == book_id), 
    )
    book = result.scalars().first()
    
    if book:
        return book
        
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")

@router.post("", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
async def create_book(book: BookCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.id == book.user_id)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="User not found",
        )
    
    new_book = models.Book(
        title = book.title,
        author = book.author, 
        genre = book.genre, 
        year = book.year, 
        rating = book.rating,
        pages = book.pages, 
        description = book.description,  
        user_id = book.user_id 
    )
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)
    
    return new_book

@router.put("/{book_id}", response_model=BookResponse)
async def update_book(book_id: int, book: BookCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Book).where(models.Book.id == book_id)
    )
    
    existing_book = result.scalars().first()
    
    if not existing_book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    if book.user_id != existing_book.user_id:
        result = await db.execute(
            select(models.User).where(models.User.id == book.user_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="User not found",
            )

    existing_book.title = book.title
    existing_book.author = book.author
    existing_book.genre = book.genre
    existing_book.year = book.year
    existing_book.rating = book.rating
    existing_book.pages = book.pages
    existing_book.description = book.description
    
    await db.commit()
    await db.refresh(existing_book)
    
    return existing_book

@router.patch("/{book_id}", response_model=BookResponse)
async def update_book_partial(book_id: int, book_data: BookUpdate, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.Book).where(models.Book.id == book_id))
    book = result.scalars().first()
    
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )
        
    update_data = book_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(book, field, value)
        
    await db.commit()
    await db.refresh(book)
    return book


@router.delete("/{book_id}")
async def delete_book(book_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Book).where(models.Book.id == book_id)
    )

    book = result.scalars().first()
    
    if book:
        await db.delete(book)
        await db.commit()
        return {"message": "Book deleted succesfully"}
        
    raise HTTPException(status_code = status.HTTP_404_NOT_FOUND, detail="Book not found")
