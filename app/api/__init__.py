"""
API Routers

All FastAPI routers for the MarketInsightsAI backend.
"""

from app.api import (
    auth,
    chat,
    folders,
    kb,
    reports,
    research,
    sessions,
    slides,
    tapestry,
    tasks,
    ws,
    # Phase 3
    agent,
    deploy,
    models,
)

__all__ = [
    "auth",
    "chat",
    "folders",
    "kb",
    "reports",
    "research",
    "sessions",
    "slides",
    "tapestry",
    "tasks",
    "ws",
    # Phase 3
    "agent",
    "deploy",
    "models",
]
