from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import settings

engine = create_async_engine(settings.build_db_url,
                             pool_pre_ping=True,
                             pool_size=100,
                             max_overflow=0
                             )
SessionLocal = async_sessionmaker(engine,
                                  expire_on_commit=False,
                                  autocommit=False,
                                  autoflush=False
                                  )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
