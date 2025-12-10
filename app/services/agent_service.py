"""
Agent Service

High-level service that integrates the multi-agent system with the application.
Provides a clean interface for using agents in API endpoints.

This service:
1. Creates and configures agent instances
2. Registers tools with executor agents
3. Manages agent lifecycles
4. Provides convenience methods for common tasks
"""

import logging
from typing import Any, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import (
    OrchestratorAgent,
    PlannerAgent,
    ExecutorAgent,
    VerifierAgent,
    AgentResult,
    TaskType,
    ToolDefinition,
    create_geocode_tool,
    create_get_tapestry_tool,
    create_search_kb_tool,
    create_generate_image_tool,
    create_store_workspace_tool,
)

logger = logging.getLogger(__name__)


class AgentService:
    """
    Service for managing and executing agents.

    Usage:
        service = AgentService(db, session_id)
        await service.setup_tools(geocode_handler, tapestry_handler, ...)
        result = await service.process_request("Generate a Tapestry report for...")
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        session_id: Optional[str] = None,
        use_planner: bool = True,
        use_verifier: bool = True,
    ):
        self.db = db
        self.session_id = session_id
        self.use_planner = use_planner
        self.use_verifier = use_verifier

        # Initialize agents
        self.orchestrator = OrchestratorAgent(db, session_id)
        self.planner = PlannerAgent(db, session_id) if use_planner else None
        self.executor = ExecutorAgent(db, session_id)
        self.verifier = VerifierAgent(db, session_id) if use_verifier else None

        # Register specialists with orchestrator
        if self.planner:
            self.orchestrator.register_specialist("planner", self.planner)
        self.orchestrator.register_specialist("executor", self.executor)
        if self.verifier:
            self.orchestrator.register_specialist("verifier", self.verifier)

    def setup_tools(
        self,
        geocode_handler: Optional[Callable] = None,
        tapestry_handler: Optional[Callable] = None,
        search_kb_handler: Optional[Callable] = None,
        generate_image_handler: Optional[Callable] = None,
        store_workspace_handler: Optional[Callable] = None,
        additional_tools: Optional[list[ToolDefinition]] = None,
    ) -> None:
        """
        Set up tools for the executor agent.

        Args:
            geocode_handler: Handler for geocode tool
            tapestry_handler: Handler for Tapestry lookup tool
            search_kb_handler: Handler for knowledge base search
            generate_image_handler: Handler for image generation
            store_workspace_handler: Handler for workspace storage
            additional_tools: Any additional tools to register
        """
        if geocode_handler:
            self.executor.register_tool(create_geocode_tool(geocode_handler))

        if tapestry_handler:
            self.executor.register_tool(create_get_tapestry_tool(tapestry_handler))

        if search_kb_handler:
            self.executor.register_tool(create_search_kb_tool(search_kb_handler))

        if generate_image_handler:
            self.executor.register_tool(create_generate_image_tool(generate_image_handler))

        if store_workspace_handler:
            self.executor.register_tool(create_store_workspace_tool(store_workspace_handler))

        if additional_tools:
            for tool in additional_tools:
                self.executor.register_tool(tool)

    async def process_request(
        self,
        request: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Process a user request using the multi-agent system.

        The orchestrator will:
        1. Classify the request
        2. Route to planner if complex
        3. Execute with executor
        4. Verify with verifier if enabled

        Args:
            request: User's request/message
            context: Optional additional context

        Returns:
            AgentResult with final output
        """
        logger.info(f"Processing request with agent system: {request[:100]}...")

        try:
            result = await self.orchestrator.execute(request, context)
            logger.info(f"Agent processing complete: success={result.success}, "
                       f"iterations={result.iterations}, tokens={result.tokens_used}")
            return result

        except Exception as e:
            logger.error(f"Agent service error: {e}")
            from app.agents import AgentState
            return AgentResult(
                success=False,
                output=f"An error occurred: {str(e)}",
                state=AgentState.ERROR,
                error=str(e),
            )

    async def execute_simple(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Execute a simple task directly with the executor (skip orchestrator).

        Use this for straightforward tasks that don't need classification.

        Args:
            task: Task description
            context: Optional context

        Returns:
            AgentResult
        """
        return await self.executor.execute(task, context)

    async def create_plan(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Create a plan without executing it.

        Useful for showing users what will happen before doing it.

        Args:
            task: Task description
            context: Optional context

        Returns:
            AgentResult with plan in output
        """
        if not self.planner:
            from app.agents import AgentState
            return AgentResult(
                success=False,
                output="Planner not enabled",
                state=AgentState.ERROR,
            )

        return await self.planner.execute(task, context)

    async def verify_output(
        self,
        original_task: str,
        output: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Verify an output's quality.

        Args:
            original_task: The original request
            output: The output to verify
            context: Optional context

        Returns:
            AgentResult with verification details
        """
        if not self.verifier:
            from app.agents import AgentState
            return AgentResult(
                success=False,
                output="Verifier not enabled",
                state=AgentState.ERROR,
            )

        verification_request = f"Verify this response:\n\nOriginal task: {original_task}\n\nResponse: {output}"
        return await self.verifier.execute(verification_request, context)

    def get_metrics(self) -> dict:
        """Get combined metrics from all agents."""
        return {
            "orchestrator": {
                "iterations": self.orchestrator.iterations,
                "tool_calls": self.orchestrator.tool_calls_made,
                "tokens": self.orchestrator.tokens_used,
            },
            "planner": {
                "iterations": self.planner.iterations if self.planner else 0,
                "tokens": self.planner.tokens_used if self.planner else 0,
            } if self.planner else None,
            "executor": {
                "iterations": self.executor.iterations,
                "tool_calls": self.executor.tool_calls_made,
                "tokens": self.executor.tokens_used,
            },
            "verifier": {
                "iterations": self.verifier.iterations if self.verifier else 0,
                "tokens": self.verifier.tokens_used if self.verifier else 0,
            } if self.verifier else None,
        }

    def reset(self) -> None:
        """Reset all agents to initial state."""
        self.orchestrator.reset()
        if self.planner:
            self.planner.reset()
        self.executor.reset()
        if self.verifier:
            self.verifier.reset()


# =============================================================================
# Convenience Functions
# =============================================================================

async def create_agent_service(
    db: AsyncSession,
    session_id: str,
    setup_default_tools: bool = True,
) -> AgentService:
    """
    Create an agent service with default configuration.

    Args:
        db: Database session
        session_id: Session ID for context
        setup_default_tools: Whether to set up default tools

    Returns:
        Configured AgentService
    """
    service = AgentService(db, session_id)

    if setup_default_tools:
        # Import handlers from existing services
        from app.services.esri_service import geocode_location, get_segment_profile
        from app.services.kb_service import search_documents
        from app.services.ai_service import generate_image
        from app.services.context import store_large_observation

        # Create wrapper handlers that match expected signatures
        async def geocode_wrapper(address: str) -> dict:
            result = await geocode_location(address)
            return result

        async def tapestry_wrapper(latitude: float, longitude: float) -> dict:
            result = await get_segment_profile(latitude, longitude)
            return result

        async def search_kb_wrapper(query: str, limit: int = 5) -> list:
            results = await search_documents(db, query, limit=limit)
            return [{"content": r.content, "source": r.source} for r in results]

        async def generate_image_wrapper(prompt: str, style: str = "photorealistic") -> dict:
            # Note: This would need to be adapted to actual image gen signature
            result = await generate_image(prompt)
            return {"image_url": result}

        async def store_workspace_wrapper(name: str, content: str, content_type: str = "text") -> dict:
            file_ref = await store_large_observation(
                db=db,
                session_id=session_id,
                observation_type=content_type,
                content=content,
                metadata={"name": name},
            )
            return {"file_id": file_ref.id, "name": name}

        service.setup_tools(
            geocode_handler=geocode_wrapper,
            tapestry_handler=tapestry_wrapper,
            search_kb_handler=search_kb_wrapper,
            generate_image_handler=generate_image_wrapper,
            store_workspace_handler=store_workspace_wrapper,
        )

    return service
