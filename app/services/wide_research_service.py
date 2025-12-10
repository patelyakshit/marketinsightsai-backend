"""
Wide Research Service

Inspired by Manus AI's "Wide Research" feature.
Spawns multiple parallel research agents to explore different
aspects of a topic simultaneously.

Features:
- Parallel agent execution
- Result aggregation
- Deduplication
- Comprehensive synthesis
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from app.utils.datetime_utils import utc_now

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.specialists import ResearchAgent
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ResearchQuery:
    """A single research query for a parallel agent."""
    id: str
    query: str
    focus_area: str
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[str] = None
    sources: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class WideResearchResult:
    """Result from wide research."""
    research_id: str
    topic: str
    total_queries: int
    completed_queries: int
    failed_queries: int
    synthesis: str
    key_findings: list[str]
    all_sources: list[dict]
    individual_results: list[ResearchQuery]
    total_duration_ms: float
    created_at: datetime = field(default_factory=utc_now)


async def generate_research_queries(
    topic: str,
    depth: str = "standard",
    context: Optional[dict] = None,
) -> list[ResearchQuery]:
    """
    Generate multiple research queries for a topic.

    Args:
        topic: Main research topic
        depth: "quick" (3 queries), "standard" (5), "comprehensive" (10)
        context: Optional context (industry, location, etc.)

    Returns:
        List of research queries
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    # Determine number of queries
    query_counts = {
        "quick": 3,
        "standard": 5,
        "comprehensive": 10,
    }
    num_queries = query_counts.get(depth, 5)

    # Build context string
    context_str = ""
    if context:
        if context.get("industry"):
            context_str += f"\nIndustry: {context['industry']}"
        if context.get("location"):
            context_str += f"\nLocation: {context['location']}"
        if context.get("focus_areas"):
            context_str += f"\nFocus areas: {', '.join(context['focus_areas'])}"

    prompt = f"""Generate {num_queries} specific research queries to comprehensively investigate this topic:

Topic: {topic}
{context_str}

For each query, provide:
1. A specific search query
2. The focus area it addresses (e.g., "market size", "competitors", "trends", "regulations", "technology")

Output as JSON array:
[
  {{"query": "specific search query", "focus_area": "area"}},
  ...
]

Make queries specific, diverse, and complementary to cover the topic thoroughly."""

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        import json
        result = json.loads(response.choices[0].message.content)
        queries_data = result if isinstance(result, list) else result.get("queries", [])

        queries = []
        for q in queries_data[:num_queries]:
            queries.append(ResearchQuery(
                id=str(uuid4()),
                query=q.get("query", ""),
                focus_area=q.get("focus_area", "general"),
            ))

        return queries

    except Exception as e:
        logger.error(f"Failed to generate research queries: {e}")
        # Fallback to basic queries
        return [
            ResearchQuery(id=str(uuid4()), query=f"{topic} overview", focus_area="overview"),
            ResearchQuery(id=str(uuid4()), query=f"{topic} latest news", focus_area="news"),
            ResearchQuery(id=str(uuid4()), query=f"{topic} market analysis", focus_area="market"),
        ]


async def execute_single_research(
    query: ResearchQuery,
    db: Optional[AsyncSession] = None,
) -> ResearchQuery:
    """
    Execute a single research query.

    Args:
        query: Research query to execute
        db: Optional database session

    Returns:
        Updated ResearchQuery with results
    """
    query.status = "running"
    query.started_at = utc_now()

    try:
        agent = ResearchAgent(db=db)
        result = await agent.execute(query.query)

        query.status = "completed"
        query.result = result.output
        query.sources = result.metadata.get("sources", [])
        query.completed_at = utc_now()

    except Exception as e:
        logger.error(f"Research query failed: {query.query} - {e}")
        query.status = "failed"
        query.error = str(e)
        query.completed_at = utc_now()

    return query


async def synthesize_results(
    topic: str,
    results: list[ResearchQuery],
) -> tuple[str, list[str]]:
    """
    Synthesize multiple research results into a comprehensive summary.

    Args:
        topic: Original topic
        results: List of completed research queries

    Returns:
        (synthesis, key_findings)
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    # Compile results
    results_text = ""
    for r in results:
        if r.status == "completed" and r.result:
            results_text += f"\n\n## {r.focus_area.title()}\n"
            results_text += f"Query: {r.query}\n"
            results_text += f"Findings:\n{r.result[:2000]}\n"

    prompt = f"""You are a research analyst. Synthesize these research findings into a comprehensive report.

Topic: {topic}

Research Findings:
{results_text}

Provide:
1. A comprehensive synthesis (3-4 paragraphs) that integrates all findings
2. A list of 5-8 key findings/insights as bullet points

Format your response as JSON:
{{
  "synthesis": "comprehensive synthesis text...",
  "key_findings": ["finding 1", "finding 2", ...]
}}"""

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        import json
        result = json.loads(response.choices[0].message.content)

        return (
            result.get("synthesis", "Unable to synthesize results."),
            result.get("key_findings", []),
        )

    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        return (
            "Research completed but synthesis failed. Please review individual results.",
            [],
        )


async def execute_wide_research(
    topic: str,
    depth: str = "standard",
    context: Optional[dict] = None,
    db: Optional[AsyncSession] = None,
    max_parallel: int = 5,
    progress_callback: Optional[callable] = None,
) -> WideResearchResult:
    """
    Execute wide research with parallel agents.

    Args:
        topic: Research topic
        depth: "quick", "standard", or "comprehensive"
        context: Optional context dict
        db: Database session
        max_parallel: Maximum concurrent research agents
        progress_callback: Optional callback for progress updates

    Returns:
        WideResearchResult with all findings
    """
    research_id = str(uuid4())
    start_time = utc_now()

    if progress_callback:
        await progress_callback(0.0, "Generating research queries...")

    # Generate queries
    queries = await generate_research_queries(topic, depth, context)

    if progress_callback:
        await progress_callback(0.1, f"Starting {len(queries)} parallel research tasks...")

    # Execute in parallel with concurrency limit
    semaphore = asyncio.Semaphore(max_parallel)

    async def limited_research(query: ResearchQuery) -> ResearchQuery:
        async with semaphore:
            return await execute_single_research(query, db)

    # Run all queries in parallel
    tasks = [limited_research(q) for q in queries]
    completed_queries = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    successful = []
    failed = 0

    for i, result in enumerate(completed_queries):
        if isinstance(result, Exception):
            queries[i].status = "failed"
            queries[i].error = str(result)
            failed += 1
        elif isinstance(result, ResearchQuery):
            queries[i] = result
            if result.status == "completed":
                successful.append(result)
            else:
                failed += 1

        if progress_callback:
            progress = 0.1 + (0.7 * (i + 1) / len(queries))
            await progress_callback(progress, f"Completed {i + 1}/{len(queries)} research tasks")

    if progress_callback:
        await progress_callback(0.8, "Synthesizing findings...")

    # Synthesize results
    synthesis, key_findings = await synthesize_results(topic, successful)

    # Collect all sources (deduplicated)
    all_sources = []
    seen_urls = set()
    for q in successful:
        for source in q.sources:
            url = source.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_sources.append(source)

    if progress_callback:
        await progress_callback(1.0, "Research complete!")

    end_time = utc_now()
    duration = (end_time - start_time).total_seconds() * 1000

    return WideResearchResult(
        research_id=research_id,
        topic=topic,
        total_queries=len(queries),
        completed_queries=len(successful),
        failed_queries=failed,
        synthesis=synthesis,
        key_findings=key_findings,
        all_sources=all_sources,
        individual_results=queries,
        total_duration_ms=duration,
    )


# =============================================================================
# Convenience Functions
# =============================================================================

async def quick_wide_research(topic: str) -> WideResearchResult:
    """Quick wide research with 3 parallel queries."""
    return await execute_wide_research(topic, depth="quick")


async def comprehensive_wide_research(
    topic: str,
    context: Optional[dict] = None,
) -> WideResearchResult:
    """Comprehensive wide research with 10 parallel queries."""
    return await execute_wide_research(
        topic,
        depth="comprehensive",
        context=context,
        max_parallel=5,
    )
