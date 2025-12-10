"""
Research API Router

Endpoints for AI-powered market research using the Research Agent.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User
from app.api.deps import get_current_user

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class ResearchRequest(BaseModel):
    """Request for market research."""
    query: str = Field(..., description="Research question or topic", min_length=5)
    location: Optional[str] = Field(None, description="Location context (city, state)")
    industry: Optional[str] = Field(None, description="Industry context")
    competitors: Optional[list[str]] = Field(None, description="Known competitors to analyze")
    async_mode: bool = Field(default=False, description="Run in background and return task ID")


class QuickSearchRequest(BaseModel):
    """Request for quick web search."""
    query: str = Field(..., description="Search query")
    max_results: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    """A single search result."""
    title: str
    url: str
    snippet: str
    domain: str


class QuickSearchResponse(BaseModel):
    """Response from quick search."""
    query: str
    results_count: int
    results: list[SearchResult]


class ResearchResponse(BaseModel):
    """Response from research task."""
    success: bool
    output: str
    sources_count: int
    sources: list[dict]
    iterations: int
    tool_calls_made: int
    duration_ms: float


class AsyncResearchResponse(BaseModel):
    """Response when research is queued."""
    task_id: str
    status: str
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/research", response_model=ResearchResponse | AsyncResearchResponse)
async def conduct_research(
    request: ResearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Conduct market research on a topic.

    The AI Research Agent will:
    1. Search the web for relevant information
    2. Extract detailed content from key pages
    3. Synthesize findings into a comprehensive report

    Set `async_mode=true` to run in background and get a task ID for polling.
    """
    # Build context
    context = {}
    if request.location:
        context["location"] = request.location
    if request.industry:
        context["industry"] = request.industry
    if request.competitors:
        context["competitors"] = request.competitors

    # Async mode - queue the task
    if request.async_mode:
        from app.services.task_queue import enqueue_research

        task_id = await enqueue_research(
            query=request.query,
            user_id=str(current_user.id),
            context=context if context else None,
        )

        return AsyncResearchResponse(
            task_id=task_id,
            status="pending",
            message="Research task queued. Poll /api/tasks/{task_id} for status.",
        )

    # Sync mode - run immediately
    from app.agents.specialists import ResearchAgent

    try:
        agent = ResearchAgent(db=db)
        result = await agent.execute(
            task=request.query,
            context=context if context else None,
        )

        return ResearchResponse(
            success=result.success,
            output=result.output,
            sources_count=result.metadata.get("sources_count", 0),
            sources=result.metadata.get("sources", []),
            iterations=result.iterations,
            tool_calls_made=result.tool_calls_made,
            duration_ms=result.duration_ms,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Research failed: {str(e)}"
        )


@router.post("/search", response_model=QuickSearchResponse)
async def quick_search(
    request: QuickSearchRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Perform a quick web search without full research analysis.

    Returns raw search results for the user to review.
    """
    from app.agents.specialists import ResearchAgent

    try:
        agent = ResearchAgent()
        results = await agent.quick_search(
            query=request.query,
            max_results=request.max_results,
        )

        return QuickSearchResponse(
            query=request.query,
            results_count=len(results),
            results=[
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("snippet", ""),
                    domain=r.get("domain", ""),
                )
                for r in results
            ],
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@router.get("/competitors/{industry}")
async def analyze_competitors(
    industry: str,
    location: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze competitors in an industry.

    Returns key competitors and market insights.
    """
    from app.agents.specialists import ResearchAgent

    query = f"Top competitors and companies in the {industry} industry"
    if location:
        query += f" in {location}"

    try:
        agent = ResearchAgent(db=db)
        result = await agent.execute(
            task=query,
            context={"industry": industry, "location": location},
        )

        return {
            "industry": industry,
            "location": location,
            "analysis": result.output,
            "sources": result.metadata.get("sources", []),
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Competitor analysis failed: {str(e)}"
        )


@router.get("/trends/{topic}")
async def research_trends(
    topic: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Research current trends for a topic.
    """
    from app.agents.specialists import ResearchAgent

    query = f"Current trends, news, and developments in {topic} in 2024"

    try:
        agent = ResearchAgent(db=db)
        result = await agent.execute(task=query)

        return {
            "topic": topic,
            "trends": result.output,
            "sources": result.metadata.get("sources", []),
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Trend research failed: {str(e)}"
        )
