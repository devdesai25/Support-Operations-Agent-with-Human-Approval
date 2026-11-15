from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Engine configuration
# connect_args={"check_same_thread": False} is required only for SQLite
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=connect_args,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing an async database session per request."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Create all registered database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
