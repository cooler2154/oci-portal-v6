# backend/db/database.py
# ---------------------------------------------------------------
# SQLAlchemy async engine + session factory.
#
# Dev:  DATABASE_URL=sqlite+aiosqlite:///./oci_portal.db
# Prod: DATABASE_URL=postgresql+psycopg://user:pass@host/db
#       (psycopg v3 — already installed as psycopg[binary])
# ---------------------------------------------------------------

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from core.config import settings

_url = settings.DATABASE_URL

# Build engine kwargs — SQLite needs check_same_thread=False
_connect_args = {"check_same_thread": False} if "sqlite" in _url else {}

engine = create_async_engine(
    _url,
    echo=(settings.APP_ENV == "development"),
    connect_args=_connect_args,
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
