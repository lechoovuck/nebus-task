from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


@lru_cache(maxsize=1)
def _session_maker():
    engine = create_async_engine(
        get_settings().database_url,
        future=True,
        pool_pre_ping=True,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with _session_maker()() as session:
        yield session
