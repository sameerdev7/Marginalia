from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

_url = make_url(settings.database_url)

# check_same_thread is a SQLite/pysqlite-ism asyncpg has no equivalent for.
# Separately: Neon (and most managed Postgres) hand out libpq-style
# connection strings with ?sslmode=require, but asyncpg's own connect()
# doesn't understand "sslmode" as a keyword — it raises a TypeError on the
# very first request. Converting it to asyncpg's own ssl= connect arg here
# means a Neon connection string can be pasted into DATABASE_URL as-is,
# with nothing to edit by hand at deploy time. Exported as CONNECT_ARGS so
# alembic/env.py's own engine can apply the same fix.
CONNECT_ARGS = {}
if _url.get_backend_name() == "sqlite":
    CONNECT_ARGS = {"check_same_thread": False}
elif "sslmode" in _url.query:
    CONNECT_ARGS = {"ssl": _url.query["sslmode"] != "disable"}
    _url = _url.difference_update_query(["sslmode"])

SQLALCHEMY_DATABASE_URL = _url.render_as_string(hide_password=False)

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=CONNECT_ARGS,
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