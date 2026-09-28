from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from config import settings
from database import engine, get_db
from schemas import BookResponse

from routers import users, books, follows, reading_logs, comments, lists, groups, posts

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup — schema is managed by alembic now, run `alembic upgrade head` before starting
    yield
    # shutdown
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

# The frontend is a separate origin in every deployed setup (and in local
# dev, :5173 vs :8000) — without this, the browser blocks every request
# before it reaches a route. Origins come from settings.cors_origins so
# production points at the real deployed frontend without a code change.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(books.router, prefix="/api/books", tags=["books"])
app.include_router(follows.router, prefix="/api/users", tags=["follows"])
app.include_router(reading_logs.router, prefix="/api/logs", tags=["logs"])
app.include_router(comments.router, prefix="/api/comments", tags=["comments"])
app.include_router(lists.router, prefix="/api/lists", tags=["lists"])
app.include_router(groups.router, prefix="/api/groups", tags=["groups"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/posts", response_class=HTMLResponse, include_in_schema=False)
async def home(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.Book))
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
async def get_books(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.Book).options(selectinload(models.Book.owner)))
    books = result.scalars().all()
    
    if not books:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No books found")
    return books


### USERS
 
# Get user books
@app.get("/api/users/{user_id}/books", response_model=list[BookResponse], status_code=status.HTTP_200_OK)
async def get_book_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.User).where(models.User.id == user_id)
    )
    user = result.scalars().first() 
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    result = await db.execute(select(models.Book).options(selectinload(models.Book.owner)).where(models.Book.user_id == user_id))
    books = result.scalars().all()
       
    return books


