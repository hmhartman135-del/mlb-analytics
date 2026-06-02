import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase


def _make_async_url(url: str) -> str:
    """
    Convert any Postgres URL variant to the asyncpg driver format.
    Railway provides: postgres://... or postgresql://...
    SQLAlchemy asyncpg needs: postgresql+asyncpg://...
    """
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


# Load .env file if present (local dev). Railway sets DATABASE_URL directly in env.
from pathlib import Path
_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# Read directly from environment — bypass pydantic entirely to avoid validation errors
_raw = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/mlb_analytics"
)
DATABASE_URL = _make_async_url(_raw)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
