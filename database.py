from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

SQLALCHEMY_DATABASE_URL = settings.database_url

# check_same_thread is a SQLite/pysqlite-ism with no equivalent (and no
# meaning) on asyncpg — only pass it when the URL is actually sqlite, so
# switching DATABASE_URL to postgresql+asyncpg:// in production doesn't
# also require touching this file.
connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=connect_args,
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