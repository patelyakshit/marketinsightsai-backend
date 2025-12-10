"""
Research Agent

Specialized agent for conducting market research, competitive analysis,
and gathering information from the web.

Capabilities:
- Web search (via DuckDuckGo - no API key required)
- URL content extraction
- Information synthesis
- Research report generation
- Integration with workspace for storing findings
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from app.utils.datetime_utils import utc_now

import httpx
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import (
    BaseAgent,
    AgentConfig,
    AgentResult,
    AgentRole,
    AgentState,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from app.config import get_settings
settings = get_settings()

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ResearchSource:
    """A source found during research."""
    url: str
    title: str
    snippet: str
    domain: str
    accessed_at: datetime = field(default_factory=utc_now)
    content: Optional[str] = None  # Full content if scraped
    relevance_score: float = 0.0


@dataclass
class ResearchResult:
    """Result of a research task."""
    query: str
    summary: str
    key_findings: list[str]
    sources: list[ResearchSource]
    raw_data: Optional[dict] = None
    created_at: datetime = field(default_factory=utc_now)


# =============================================================================
# Web Search Implementation (DuckDuckGo - No API Key Required)
# =============================================================================

async def duckduckgo_search(
    query: str,
    max_results: int = 10,
    region: str = "us-en",
) -> list[dict]:
    """
    Search DuckDuckGo for results.

    Uses DuckDuckGo's HTML interface (no API key needed).

    Args:
        query: Search query
        max_results: Maximum results to return
        region: Region code (e.g., "us-en", "uk-en")

    Returns:
        List of search results with title, url, snippet
    """
    results = []

    try:
        # DuckDuckGo HTML search URL
        search_url = "https://html.duckduckgo.com/html/"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                search_url,
                data={"q": query, "kl": region},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            response.raise_for_status()
            html = response.text

            # Parse results using regex (lightweight, no BeautifulSoup needed)
            # Find result blocks
            result_pattern = r'<a class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>.*?<a class="result__snippet"[^>]*>([^<]+)</a>'
            matches = re.findall(result_pattern, html, re.DOTALL)

            for url, title, snippet in matches[:max_results]:
                # Clean up the URL (DuckDuckGo wraps URLs)
                if url.startswith("//duckduckgo.com/l/"):
                    # Extract actual URL from DDG redirect
                    url_match = re.search(r'uddg=([^&]+)', url)
                    if url_match:
                        from urllib.parse import unquote
                        url = unquote(url_match.group(1))

                results.append({
                    "title": title.strip(),
                    "url": url,
                    "snippet": snippet.strip(),
                    "domain": urlparse(url).netloc if url.startswith("http") else "",
                })

    except Exception as e:
        logger.error(f"DuckDuckGo search error: {e}")
        # Return empty results on error - agent will handle gracefully

    return results


async def scrape_url_content(
    url: str,
    max_length: int = 10000,
) -> dict:
    """
    Scrape content from a URL.

    Args:
        url: URL to scrape
        max_length: Maximum content length to return

    Returns:
        Dict with title, content, and metadata
    """
    result = {
        "url": url,
        "title": "",
        "content": "",
        "success": False,
        "error": None,
    }

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            response.raise_for_status()
            html = response.text

            # Extract title
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            if title_match:
                result["title"] = title_match.group(1).strip()

            # Remove script and style tags
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)

            # Remove HTML tags and get text
            text = re.sub(r'<[^>]+>', ' ', html)

            # Clean whitespace
            text = re.sub(r'\s+', ' ', text).strip()

            # Truncate if too long
            if len(text) > max_length:
                text = text[:max_length] + "..."

            result["content"] = text
            result["success"] = True

    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
    except httpx.RequestError as e:
        result["error"] = f"Request failed: {str(e)}"
    except Exception as e:
        result["error"] = str(e)

    return result


# =============================================================================
# Research Agent
# =============================================================================

class ResearchAgent(BaseAgent):
    """
    Specialist agent for conducting research.

    Can search the web, extract content from URLs, synthesize information,
    and produce research reports.
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        session_id: Optional[str] = None,
    ):
        config = AgentConfig(
            name="research",
            role=AgentRole.SPECIALIST,
            model=settings.openai_model,
            temperature=0.7,
            max_tokens=4096,
            max_iterations=20,  # Research may need more iterations
            parallel_tool_calls=True,
        )
        super().__init__(config, db, session_id)

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.sources_found: list[ResearchSource] = []

        # Register research tools
        self._register_research_tools()

    def _register_research_tools(self) -> None:
        """Register tools for research."""
        self.register_tools([
            create_web_search_tool(self._handle_web_search),
            create_scrape_url_tool(self._handle_scrape_url),
            create_save_finding_tool(self._handle_save_finding),
        ])

    async def _handle_web_search(
        self,
        query: str,
        max_results: int = 10,
    ) -> dict:
        """Handle web search tool call."""
        results = await duckduckgo_search(query, max_results)

        # Track sources
        for r in results:
            self.sources_found.append(ResearchSource(
                url=r["url"],
                title=r["title"],
                snippet=r["snippet"],
                domain=r["domain"],
            ))

        return {
            "query": query,
            "results_count": len(results),
            "results": results,
        }

    async def _handle_scrape_url(
        self,
        url: str,
        max_length: int = 10000,
    ) -> dict:
        """Handle URL scraping tool call."""
        result = await scrape_url_content(url, max_length)

        # Update source if we have it
        for source in self.sources_found:
            if source.url == url:
                source.content = result.get("content")
                break

        return result

    async def _handle_save_finding(
        self,
        finding: str,
        source_url: Optional[str] = None,
        category: str = "general",
    ) -> dict:
        """Handle saving a research finding to workspace."""
        if self.db and self.session_id:
            from app.services.context import store_workspace_file

            filename = f"finding_{category}_{utc_now().strftime('%H%M%S')}.txt"
            content = f"Finding: {finding}\n"
            if source_url:
                content += f"Source: {source_url}\n"
            content += f"Category: {category}\n"
            content += f"Recorded: {utc_now().isoformat()}\n"

            await store_workspace_file(
                db=self.db,
                session_id=self.session_id,
                filename=filename,
                content=content,
                file_type="research_finding",
            )

            return {"saved": True, "filename": filename}

        return {"saved": False, "reason": "No session context"}

    def get_system_prompt(self) -> str:
        return """You are a Research Agent for MarketInsightsAI.

Your role is to conduct thorough market research, competitive analysis, and gather business intelligence.

## Capabilities

1. **Web Search**: Search the internet for relevant information
2. **URL Scraping**: Extract detailed content from specific web pages
3. **Finding Storage**: Save important findings for later reference

## Research Guidelines

1. **Start Broad, Then Narrow**: Begin with general searches, then dive deeper into relevant results
2. **Verify Information**: Cross-reference findings from multiple sources when possible
3. **Source Quality**: Prefer authoritative sources (official sites, news, research papers)
4. **Stay Focused**: Keep research relevant to the user's query
5. **Summarize Effectively**: Synthesize findings into actionable insights

## Research Process

1. Understand the research question
2. Plan search queries (consider multiple angles)
3. Execute searches
4. Evaluate and select relevant results
5. Scrape key pages for detailed information
6. Synthesize findings
7. Present a comprehensive summary with sources

## Output Format

When completing research, provide:
- **Summary**: 2-3 paragraph overview of findings
- **Key Findings**: Bullet points of the most important discoveries
- **Sources**: List of sources with their relevance
- **Recommendations**: If applicable, actionable recommendations

## Error Handling

If searches fail:
1. Try alternative search queries
2. Use different phrasing or keywords
3. Report what you were unable to find

Always be honest about limitations and confidence in findings.
"""

    async def execute(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Execute a research task.

        Args:
            task: Research question or topic
            context: Optional context (location, industry, etc.)

        Returns:
            AgentResult with research findings
        """
        self.start_time = utc_now()
        self.set_state(AgentState.EXECUTING)
        self.sources_found = []  # Reset sources

        try:
            # Load session context if available
            await self.load_session_context()

            # Add system prompt
            if not any(m.role.value == "system" for m in self.messages):
                self.add_system_message(self.get_system_prompt())

            # Add context if provided
            if context:
                context_str = "\n## Research Context\n"
                if "location" in context:
                    context_str += f"- Location: {context['location']}\n"
                if "industry" in context:
                    context_str += f"- Industry: {context['industry']}\n"
                if "competitors" in context:
                    context_str += f"- Known Competitors: {', '.join(context['competitors'])}\n"
                self.add_system_message(context_str)

            # Add the research task
            self.add_user_message(f"Research Task: {task}")

            # Execute research loop
            result = await self._research_loop()

            # Add sources to result metadata
            result.metadata["sources"] = [
                {
                    "url": s.url,
                    "title": s.title,
                    "domain": s.domain,
                }
                for s in self.sources_found
            ]
            result.metadata["sources_count"] = len(self.sources_found)

            # Save result to session
            await self.save_result_to_session(result)

            return result

        except Exception as e:
            logger.error(f"Research agent error: {e}")
            self.set_state(AgentState.ERROR)

            return AgentResult(
                success=False,
                output=f"Research failed: {str(e)}",
                state=AgentState.ERROR,
                iterations=self.iterations,
                tool_calls_made=self.tool_calls_made,
                tokens_used=self.tokens_used,
                duration_ms=self.get_duration_ms(),
                error=str(e),
            )

    async def _research_loop(self) -> AgentResult:
        """
        Main research loop with tool calling.
        """
        final_output = ""

        while not self.should_stop():
            self.iterations += 1

            # Generate next action
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=self.get_messages_for_api(),
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                tools=self.get_tools_for_api() or None,
                tool_choice="auto" if self.tools else None,
                parallel_tool_calls=self.config.parallel_tool_calls,
            )

            self.tokens_used += response.usage.total_tokens
            message = response.choices[0].message

            # Handle tool calls
            if message.tool_calls:
                self.add_assistant_message(
                    content=message.content or "",
                    tool_calls=[tc.model_dump() for tc in message.tool_calls]
                )

                # Execute tools
                tool_calls = [ToolCall.from_openai(tc.model_dump()) for tc in message.tool_calls]

                if self.config.parallel_tool_calls and len(tool_calls) > 1:
                    results = await self.execute_parallel_tools(tool_calls)
                else:
                    results = []
                    for tc in tool_calls:
                        results.append(await self.execute_tool(tc))

                # Add results to messages
                for result in results:
                    self.messages.append(result.to_message())

                continue

            # Final response
            final_output = message.content or ""
            self.add_assistant_message(final_output)

            self.set_state(AgentState.COMPLETE)
            break

        return AgentResult(
            success=True,
            output=final_output,
            state=self.state,
            iterations=self.iterations,
            tool_calls_made=self.tool_calls_made,
            tokens_used=self.tokens_used,
            duration_ms=self.get_duration_ms(),
        )

    async def quick_search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """
        Perform a quick search without full agent loop.

        Args:
            query: Search query
            max_results: Maximum results

        Returns:
            List of search results
        """
        return await duckduckgo_search(query, max_results)


# =============================================================================
# Tool Factory Functions
# =============================================================================

def create_web_search_tool(handler: Callable) -> ToolDefinition:
    """Create web search tool definition."""
    return ToolDefinition(
        name="web_search",
        description="Search the web for information. Returns titles, URLs, and snippets from relevant web pages.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        },
        handler=handler,
        estimated_duration=3.0,
    )


def create_scrape_url_tool(handler: Callable) -> ToolDefinition:
    """Create URL scraping tool definition."""
    return ToolDefinition(
        name="scrape_url",
        description="Extract the main text content from a web page URL. Use this to get detailed information from a specific page found in search results.",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to scrape"
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum content length (default: 10000)",
                    "default": 10000
                }
            },
            "required": ["url"]
        },
        handler=handler,
        estimated_duration=5.0,
    )


def create_save_finding_tool(handler: Callable) -> ToolDefinition:
    """Create tool for saving research findings."""
    return ToolDefinition(
        name="save_finding",
        description="Save an important research finding to the workspace for later reference",
        parameters={
            "type": "object",
            "properties": {
                "finding": {
                    "type": "string",
                    "description": "The finding or insight to save"
                },
                "source_url": {
                    "type": "string",
                    "description": "URL of the source (optional)"
                },
                "category": {
                    "type": "string",
                    "description": "Category (e.g., 'competitor', 'market', 'trend')",
                    "default": "general"
                }
            },
            "required": ["finding"]
        },
        handler=handler,
    )
