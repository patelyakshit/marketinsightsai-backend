from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
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
            print("pgvector extension enabled")
            pgvector_available = True
        except Exception as e:
            print(f"Warning: Could not enable pgvector extension: {e}")
            print("Vector search features may not work")

        # Create all tables
        try:
            await conn.run_sync(Base.metadata.create_all)
            print("All tables created successfully")
        except Exception as e:
            print(f"Error creating tables: {e}")
            # If pgvector failed and table creation failed, try without vector tables
            if not pgvector_available:
                print("Attempting to create tables without vector columns...")
                # Create tables one by one, skipping problematic ones
                for table in Base.metadata.sorted_tables:
                    try:
                        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
                        print(f"  Created table: {table.name}")
                    except Exception as table_error:
                        print(f"  Skipped table {table.name}: {table_error}")
