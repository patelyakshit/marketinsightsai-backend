import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import get_settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from app.api import (
    chat, reports, kb, auth, folders, sessions, ws,
    slides, tapestry, research, tasks,
    agent, deploy, models,  # Phase 3
)
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
        logger.info(f"Sentry initialized for environment: {settings.sentry_environment}")
    except ImportError:
        logger.warning("sentry-sdk not installed. Error monitoring disabled.")
    except Exception as e:
        logger.warning(f"Sentry initialization failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.app_name}...")

    # Initialize database tables in background - don't block startup
    import asyncio
    async def init_database():
        try:
            logger.info("Initializing database tables...")
            await init_db()
            logger.info("Database tables initialized.")
        except Exception as e:
            logger.warning(f"Database initialization failed: {e}")
            logger.warning("App will continue but database features may not work")

    # Create task but don't await - let app start immediately
    # Using callback to ensure exceptions are logged (not silently swallowed)
    from app.utils.async_utils import create_task_with_error_handling
    create_task_with_error_handling(init_database(), task_name="database_init")

    # Initialize task queue handlers
    try:
        from app.services.task_queue import init_task_handlers
        init_task_handlers()
        logger.info("Task queue handlers initialized.")
    except Exception as e:
        logger.warning(f"Task queue initialization failed: {e}")

    yield
    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(
    title="MarketInsightsAI API",
    description="Backend API for MarketInsightsAI - Autonomous AI Agent for Location Intelligence, Tapestry Reports, and Knowledge Base",
    version="0.2.0",
    lifespan=lifespan,
)

# Rate limiting setup
from slowapi.errors import RateLimitExceeded
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS middleware - origins from environment variable
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
logger.info(f"CORS Origins configured: {cors_origins}")

# Explicitly list allowed headers instead of "*" for security
# These are the headers actually used by the frontend
CORS_ALLOWED_HEADERS = [
    "Accept",
    "Accept-Language",
    "Authorization",
    "Content-Type",
    "Origin",
    "X-Requested-With",
]

# Headers the frontend may need to read from responses
CORS_EXPOSE_HEADERS = [
    "Content-Length",
    "Content-Type",
    "X-Request-Id",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=CORS_ALLOWED_HEADERS,
    expose_headers=CORS_EXPOSE_HEADERS,
    max_age=600,
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(kb.router, prefix="/api/kb", tags=["Knowledge Base"])
app.include_router(folders.router, prefix="/api", tags=["Folders"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(ws.router, prefix="/api/ws", tags=["WebSocket"])
app.include_router(slides.router, prefix="/api/slides", tags=["Slides"])
app.include_router(tapestry.router, prefix="/api/tapestry", tags=["Tapestry"])
app.include_router(research.router, prefix="/api/research", tags=["Research"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks"])

# Phase 3: Advanced Features
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(deploy.router, prefix="/api/deploy", tags=["Deploy"])
app.include_router(models.router, prefix="/api/models", tags=["Models"])



@app.get("/", tags=["Health"])
@app.get("/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
async def health_check():
    """Health check endpoint - available at /, /health, and /api/health"""
    return {"status": "healthy", "app": settings.app_name}
