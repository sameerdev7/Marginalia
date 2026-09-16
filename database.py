from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase


SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./marginalia.db"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
)

SessionLocal = async_sessionmaker(
    engine, 
    class_= AsyncSession, 
    expire_on_commit=False, 
)


class Base(DeclarativeBase):
    pass 

async def get_db():
    async with SessionLocal() as db:
        yield db 