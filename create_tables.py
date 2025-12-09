"""Script to create all database tables."""
import asyncio
from sqlalchemy import text
from app.db.database import engine, Base
from app.db.models import (
    User, Team, TeamMember, SavedReport, ReportTemplate,
    Workspace, KnowledgeDocument, TapestrySegment, Store,
    StoreSegmentData, GeneratedReport
)

async def create_tables():
    """Create all tables in the database."""
    async with engine.begin() as conn:
        # Create pgvector extension first (needed for embeddings)
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully!")

if __name__ == "__main__":
    asyncio.run(create_tables())
