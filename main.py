from typing import Annotated

from fastapi import FastAPI, HTTPException, status, Depends 
from fastapi.responses import HTMLResponse

from sqlalchemy import select 
from sqlalchemy.orm import Session

import models 
from database import Base, engine, get_db
from schemas import BookCreate, BookResponse, UserCreate, UserResponse

Base.metadata.create_all(engine)

app = FastAPI() 

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/posts", response_class=HTMLResponse, include_in_schema=False)
def home(db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(models.Book))
    books = result.scalars().all()
    return """
    <html>
        <head>
            <title>Books</title>
        </head>
        <body>
            <h1>Hello from FastAPI!</h1>
            <p>Home route is working.</p>
        </body>
    </html>
    """


@app.get("/api/books")
def get_books(db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(models.Book))
    books = result.scalars().all()
    return books


@app.get("/api/books/{book_id}")
def get_book(book_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.Book).where(models.Book.id == book_id), 
    )
    book = result.scalars().first()
    
    if book:
        return book
        
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")

@app.post("/api/books")
def create_book(book: BookCreate, db: Annotated[Session, Depends(get_db)]):
    new_book = models.Book(
        title = book.title,
        author = book.author, 
        genre = book.genre, 
        year = book.year, 
        rating = book.rating,
        pages = book.pages, 
        description = book.description,  
        user_id = 1 # temporary
    )
    db.add(new_book)
    db.commit()
    db.refresh(new_book)
    
    return new_book