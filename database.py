from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

_url = make_url(settings.database_url)

# check_same_thread is a SQLite/pysqlite-ism asyncpg has no equivalent for.
# Separately: Neon (and most managed Postgres) hand out libpq-style
# connection strings carrying ?sslmode=require&channel_binding=require, but
# asyncpg's own connect() doesn't understand either as a keyword — it raises
# a TypeError on the very first request. Converting sslmode into asyncpg's
# own ssl= connect arg (and dropping channel_binding, which asyncpg has no
# equivalent for — TLS is already enforced via ssl=) means a Neon connection
# string can be pasted into DATABASE_URL as-is, nothing to edit by hand at
# deploy time. Exported as CONNECT_ARGS so alembic/env.py's own engine
# applies the same fix.
CONNECT_ARGS = {}
if _url.get_backend_name() == "sqlite":
    CONNECT_ARGS = {"check_same_thread": False}
elif _url.get_backend_name() == "postgresql":
    if "sslmode" in _url.query:
        CONNECT_ARGS["ssl"] = _url.query["sslmode"] != "disable"
    # Neon's pooled endpoint (hostname has "-pooler" in it) routes through
    # PgBouncer in transaction mode, which doesn't guarantee the same
    # physical server connection between statements — asyncpg's default
    # prepared-statement cache then intermittently errors with "prepared
    # statement ... does not exist". Disabling it costs a small amount of
    # performance and fixes the pooler; a direct (non-pooled) connection is
    # unaffected either way, so this is always safe to set.
    CONNECT_ARGS["statement_cache_size"] = 0
    _url = _url.difference_update_query(["sslmode", "channel_binding"])

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