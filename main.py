from typing import Annotated

from fastapi import FastAPI, HTTPException, status, Depends 
from fastapi.responses import HTMLResponse

from sqlalchemy import select 
from sqlalchemy.orm import Session

import models 
from database import Base, engine, get_db
from schemas import BookCreate, BookResponse, UserCreate, UserResponse, BookUpdate, UserUpdate

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


## book endpoints 

@app.get("/api/books", response_model=list[BookResponse])
def get_books(db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(models.Book))
    books = result.scalars().all()
    
    if not books:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No books found")
    return books


@app.get("/api/books/{book_id}", response_model=BookResponse)
def get_book(book_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.Book).where(models.Book.id == book_id), 
    )
    book = result.scalars().first()
    
    if book:
        return book
        
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")

@app.post("/api/books", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
def create_book(book: BookCreate, db: Annotated[Session, Depends(get_db)]):
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
    db.commit()
    db.refresh(new_book)
    
    return new_book

@app.put("/api/books/{book_id}", response_model=BookResponse)
def update_book(book_id: int, book: BookCreate, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.Book).where(models.Book.id == book_id)
    )
    
    existing_book = result.scalars().first()
    
    if not existing_book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    if book.user_id != book.user_id:
        result = db.execute(
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
    
    db.commit()
    db.refresh(existing_book)
    
    return existing_book

@app.patch("/api/books/{book_id}", response_model=BookResponse)
def update_book_partial(book_id: int, book_data: BookUpdate, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(select(models.Book).where(models.Book.id == book_id))
    book = result.scalars().first()
    
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )
        
    update_data = book_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(book, field, value)
        
    db.commit()
    db.refresh(book)
    return book


@app.delete("api/books/{book_id}")
def delete_book(book_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.Book).where(models.Book.id == book_id)
    )

    book = result.scalars().first()
    
    if book:
        db.delete(book)
        db.commit()
        return {"message": "Book deleted succesfully"}
        
    raise HTTPException(status_code = status.HTTP_404_NOT_FOUND, detail="Book not found")


### USERS 

# Create user 
@app.post("/api/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, db: Annotated[Session, Depends(get_db)]):
    new_user = models.User(
        username = user.username, 
        email = user.email
    )
    
    db.add(new_user)
    db.commit() 
    db.refresh(new_user)
    
    return new_user

# Get user 
@app.get("/api/users/{user_id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
def get_user(user_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalars().first()
    if user:
        return user 
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


# Get all users 
@app.get("/api/users", response_model=list[UserResponse], status_code=status.HTTP_200_OK)
def get_users(db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.User)
    )
    users = result.scalars().all()
    
    if users:
        return users 
    
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No users found")

@app.patch("/api/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, update_user: UserUpdate, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    if update_user.username is not None and update_user.username != user.username:
        result = db.execute(
            select(models.User).where(models.User.username == update_user.username)
        )
        existing_user = result.scalars().first()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="User already exists"
            )
            
        
    if update_user.email is not None and update_user.email != user.email:
        result = db.execute(
            select(models.User).where(models.User.email == update_user.email)
        )
        
        existing_email = result.scalars().first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists"
            )
            
    if update_user.username is not None:
        user.username = update_user.username

    if update_user.email is not None:
        user.email = update_user.email
        
        
    db.commit()
    db.refresh(user)
    return user

@app.delete("/api/users/{user_id}", status_code=status.HTTP_200_OK)
def delete_user(user_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    
    user = result.scalars().first()
    
    if user:
        db.delete(user)
        db.commit()
        return {"message": "User deleted successfully"}
        
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
 
# Get user books
@app.get("/api/users/{user_id}/books", response_model=list[BookResponse], status_code=status.HTTP_200_OK)
def get_book_user(user_id: int, db: Annotated[Session, Depends(get_db)]):
    result = db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalars().first() 
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    result = db.execute(select(models.Book).where(models.Book.user_id == user_id))
    books = result.scalars().all()
       
    return books