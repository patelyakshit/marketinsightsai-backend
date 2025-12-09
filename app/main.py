from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import get_settings
from app.api import chat, reports, kb, auth, folders, sessions
from app.db.database import init_db

# Initialize settings early for Sentry
settings = get_settings()

# Initialize Sentry (must be before FastAPI app creation for proper error capture)
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
            # Capture 100% of transactions for performance monitoring
            traces_sample_rate=1.0 if settings.debug else 0.2,
            # Associate users with errors
            send_default_pii=True,
        )
        print(f"Sentry initialized for environment: {settings.sentry_environment}")
    except ImportError:
        print("WARNING: sentry-sdk not installed. Error monitoring disabled.")
    except Exception as e:
        print(f"WARNING: Sentry initialization failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"Starting {settings.app_name}...")

    # Initialize database tables in background - don't block startup
    import asyncio
    async def init_database():
        try:
            print("Initializing database tables...")
            await init_db()
            print("Database tables initialized.")
        except Exception as e:
            print(f"WARNING: Database initialization failed: {e}")
            print("App will continue but database features may not work")

    # Create task but don't await - let app start immediately
    asyncio.create_task(init_database())

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
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
print(f"CORS Origins configured: {cors_origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(kb.router, prefix="/api/kb", tags=["Knowledge Base"])
app.include_router(folders.router, prefix="/api", tags=["Folders"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])



@app.get("/")
async def root():
    """Root endpoint for basic health check"""
    return {"status": "ok"}


@app.get("/health")
async def health():
    """Simple health check at /health"""
    return {"status": "healthy"}


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "app": get_settings().app_name}
