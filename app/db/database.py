import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    # Connection pool settings for production stability
    pool_size=5,           # Default number of connections to maintain
    max_overflow=10,       # Additional connections under high load
    pool_timeout=30,       # Seconds to wait for available connection
    pool_recycle=1800,     # Recycle connections after 30 minutes
    # Disable statement caching for pgbouncer compatibility (Supabase uses pgbouncer)
    connect_args={"statement_cache_size": 0},
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    # Import models to ensure they're registered with Base
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        # Try to enable pgvector extension (may fail on some hosts)
        pgvector_available = False
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            logger.info("pgvector extension enabled")
            pgvector_available = True
        except Exception as e:
            logger.warning(f"Could not enable pgvector extension: {e}")
            logger.warning("Vector search features may not work")

        # Create all tables
        try:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("All tables created successfully")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            # If pgvector failed and table creation failed, try without vector tables
            if not pgvector_available:
                logger.info("Attempting to create tables without vector columns...")
                # Create tables one by one, skipping problematic ones
                for table in Base.metadata.sorted_tables:
                    try:
                        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
                        logger.info(f"  Created table: {table.name}")
                    except Exception as table_error:
                        logger.warning(f"  Skipped table {table.name}: {table_error}")
