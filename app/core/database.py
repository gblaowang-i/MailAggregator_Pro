from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


settings = get_settings()


def _configure_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def get_engine() -> AsyncEngine:
    db_url = str(settings.database_url)
    url = make_url(db_url)
    is_sqlite = url.drivername.split("+", 1)[0] == "sqlite"
    connect_args = {}
    if is_sqlite:
        connect_args["timeout"] = 15
        if url.database and url.database != ":memory:":
            p = Path(url.database)
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)

    eng = create_async_engine(db_url, echo=False, future=True, connect_args=connect_args)
    if is_sqlite:
        event.listen(eng.sync_engine, "connect", _configure_sqlite_pragmas)
    return eng


engine = get_engine()
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


