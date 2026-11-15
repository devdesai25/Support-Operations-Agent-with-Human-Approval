from collections.abc import AsyncGenerator
from fastapi import Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session per request."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def verify_approval_api_key(x_api_key: str = Header(..., description="Secret operational API key")):
    """Ensure operator/supervisor endpoints require explicit API-key authorization."""
    if x_api_key != settings.approval_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )
    return x_api_key
