from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import get_settings
from app.api import chat, reports, kb, auth, folders
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    print(f"Starting {settings.app_name}...")
    print(f"Database URL: {settings.database_url[:50]}...")  # Print partial URL for debugging

    # Initialize database tables
    try:
        print("Initializing database tables...")
        await init_db()
        print("Database tables initialized.")
    except Exception as e:
        print(f"WARNING: Database initialization failed: {e}")
        print("App will start but database features may not work")

    yield
    # Shutdown
    print("Shutting down...")


app = FastAPI(
    title="MarketInsightsAI API",
    description="Backend API for MarketInsightsAI - Autonomous AI Agent for Location Intelligence, Tapestry Reports, and Knowledge Base",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS middleware - origins from environment variable
settings = get_settings()
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(kb.router, prefix="/api/kb", tags=["Knowledge Base"])
app.include_router(folders.router, prefix="/api", tags=["Folders"])



@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "app": get_settings().app_name}
