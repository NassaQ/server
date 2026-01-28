from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import OperationalError
from app.core.config import settings
import asyncio
import logging

logger = logging.getLogger("SQL SERVER")

engine = create_async_engine(
    settings.SQL_CONNECTION_STRING,  # type: ignore
    connect_args={"timeout": settings.SQL_CONNECT_TIMEOUT},
    pool_pre_ping=True,
    pool_recycle=1800,
)

AsyncSessionLocal = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db():
    """
    Database session dependency with retry logic for Azure SQL cold starts.

    Implements exponential backoff retry to handle connection timeouts
    that occur when Azure SQL Database is waking up from a paused state.
    """
    last_exception = None

    for attempt in range(1, settings.SQL_MAX_RETRIES + 1):
        try:
            async with AsyncSessionLocal() as session:
                yield session
                return
        except OperationalError as e:
            last_exception = e
            if attempt < settings.SQL_MAX_RETRIES:
                delay = settings.SQL_RETRY_DELAY_BASE**attempt
                logger.warning(
                    f"Database connection failed (attempt {attempt}/{settings.SQL_MAX_RETRIES}). "
                    f"Retrying in {delay}s... Error: {e}"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"Database connection failed after {settings.SQL_MAX_RETRIES} attempts. Error: {e}"
                )

    raise last_exception
