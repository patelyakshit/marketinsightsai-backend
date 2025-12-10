"""
Specialist Agents

Domain-specific agents that extend the base agent capabilities.
Each specialist has deep knowledge and tools for a particular domain.
"""

from app.agents.specialists.research_agent import (
    ResearchAgent,
    ResearchResult,
    ResearchSource,
    create_web_search_tool,
    create_scrape_url_tool,
)

__all__ = [
    "ResearchAgent",
    "ResearchResult",
    "ResearchSource",
    "create_web_search_tool",
    "create_scrape_url_tool",
]
