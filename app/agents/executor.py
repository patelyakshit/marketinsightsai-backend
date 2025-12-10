"""
Executor Agent

Executes plans and tool calls with proper error handling.
The workhorse agent that actually performs actions.

Inspired by Manus AI's execution approach:
- Tool orchestration
- Error recovery
- Progress tracking
- Result aggregation
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.utils.datetime_utils import utc_now

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


@dataclass
class ExecutionStep:
    """A single execution step with result."""
    step_id: str
    description: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Any = None
    error: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


class ExecutorAgent(BaseAgent):
    """
    Executor agent that performs actions and tool calls.

    Responsibilities:
    1. Execute plan steps in order
    2. Handle tool calls with the AI model
    3. Track progress and update goals
    4. Handle errors with retries
    5. Store large results in workspace
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        session_id: Optional[str] = None,
    ):
        config = AgentConfig(
            name="executor",
            role=AgentRole.EXECUTOR,
            model=settings.openai_model,
            temperature=0.7,
            max_tokens=4096,
            max_iterations=15,  # Higher for complex executions
            parallel_tool_calls=True,
        )
        super().__init__(config, db, session_id)

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.execution_history: list[ExecutionStep] = []

    def get_system_prompt(self) -> str:
        return """You are the Executor agent for MarketInsightsAI.

Your role is to carry out tasks using the available tools and your knowledge.

## Execution Guidelines

1. **Be Thorough**: Complete each step fully before moving on
2. **Use Tools Wisely**: Call tools when needed, don't guess at data
3. **Handle Errors**: If a tool fails, explain what went wrong and try alternatives
4. **Track Progress**: Update goals as you complete steps
5. **Store Large Data**: Use workspace for large results that shouldn't clutter context

## Available Context

- You may have a plan from the Planner agent with steps to follow
- You have access to conversation history
- You can see active goals that need completion

## Response Format

When completing a task:
1. Acknowledge what you're doing
2. Use tools as needed
3. Summarize results clearly
4. Indicate which goals were completed

## Error Handling

If something fails:
1. Note the error clearly
2. Try an alternative approach if available
3. If stuck, explain what you tried and what didn't work

Always be helpful and provide value even if some steps fail.
"""

    async def execute(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Execute a task, optionally following a plan.

        Args:
            task: Task description or user message
            context: Optional context with plan, classification, etc.

        Returns:
            AgentResult with execution outcome
        """
        self.start_time = utc_now()
        self.set_state(AgentState.EXECUTING)

        try:
            # Load session context if available
            await self.load_session_context()

            # Add system prompt
            if not any(m.role.value == "system" for m in self.messages):
                self.add_system_message(self.get_system_prompt())

            # Add context from plan if available
            if context and "plan" in context:
                self.add_system_message(f"\n## Execution Plan\n{context['plan']}")

            # Add the user task
            self.add_user_message(task)

            # Execute with agentic loop
            result = await self._agentic_loop()

            # Save result to session
            await self.save_result_to_session(result)

            return result

        except Exception as e:
            logger.error(f"Executor error: {e}")
            self.set_state(AgentState.ERROR)

            return AgentResult(
                success=False,
                output=f"Execution failed: {str(e)}",
                state=AgentState.ERROR,
                iterations=self.iterations,
                tool_calls_made=self.tool_calls_made,
                tokens_used=self.tokens_used,
                duration_ms=self.get_duration_ms(),
                error=str(e),
            )

    async def _agentic_loop(self) -> AgentResult:
        """
        Run the agentic loop: generate -> tools -> observe -> repeat.

        This is the core execution loop inspired by ReAct pattern.
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

            # Check for tool calls
            if message.tool_calls:
                # Add assistant message with tool calls
                self.add_assistant_message(
                    content=message.content or "",
                    tool_calls=[tc.model_dump() for tc in message.tool_calls]
                )

                # Execute all tool calls
                tool_calls = [ToolCall.from_openai(tc.model_dump()) for tc in message.tool_calls]

                if self.config.parallel_tool_calls and len(tool_calls) > 1:
                    results = await self.execute_parallel_tools(tool_calls)
                else:
                    results = []
                    for tc in tool_calls:
                        results.append(await self.execute_tool(tc))

                # Add tool results to messages
                for result in results:
                    self.messages.append(result.to_message())

                # Continue loop to process tool results
                continue

            # No tool calls - we have a final response
            final_output = message.content or ""
            self.add_assistant_message(final_output)

            # Check if we should continue or complete
            if self._is_complete(final_output):
                self.set_state(AgentState.COMPLETE)
                break

        # Update any completed goals
        goals_completed = await self._update_completed_goals(final_output)

        return AgentResult(
            success=True,
            output=final_output,
            state=self.state,
            iterations=self.iterations,
            tool_calls_made=self.tool_calls_made,
            tokens_used=self.tokens_used,
            duration_ms=self.get_duration_ms(),
            goals_completed=goals_completed,
        )

    def _is_complete(self, output: str) -> bool:
        """
        Determine if execution is complete.

        Can be overridden for more sophisticated completion detection.
        """
        # Simple heuristic: if we generated output without tool calls, we're done
        return bool(output.strip())

    async def _update_completed_goals(self, output: str) -> list[str]:
        """
        Update goals based on completion.

        Uses the goal service to mark completed goals.
        """
        if not self.db or not self.session_id:
            return []

        from app.services.context import (
            get_active_goals,
            complete_goal,
            parse_goals_from_response,
        )

        completed = []

        try:
            # Get active goals
            active_goals = await get_active_goals(self.db, self.session_id)

            # Check each goal against output (simple heuristic)
            for goal in active_goals:
                # If the output mentions completing this goal's text
                if goal.goal_text.lower() in output.lower():
                    await complete_goal(self.db, goal.id)
                    completed.append(goal.goal_text)

            # Also try to parse any new goals from the response
            new_goals = await parse_goals_from_response(output)
            # These would be added by the planner, so we just note them here

        except Exception as e:
            logger.warning(f"Goal update error: {e}")

        return completed


# =============================================================================
# Pre-built Tools for Executor
# =============================================================================

def create_geocode_tool(handler: Callable) -> ToolDefinition:
    """Create geocode tool definition."""
    return ToolDefinition(
        name="geocode",
        description="Convert an address or place name to geographic coordinates (latitude, longitude)",
        parameters={
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "The address or place name to geocode"
                }
            },
            "required": ["address"]
        },
        handler=handler,
    )


def create_get_tapestry_tool(handler: Callable) -> ToolDefinition:
    """Create Tapestry segment lookup tool."""
    return ToolDefinition(
        name="get_tapestry",
        description="Get Esri Tapestry segmentation data for a location. Returns consumer segment profile.",
        parameters={
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Latitude of the location"
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude of the location"
                }
            },
            "required": ["latitude", "longitude"]
        },
        handler=handler,
    )


def create_search_kb_tool(handler: Callable) -> ToolDefinition:
    """Create knowledge base search tool."""
    return ToolDefinition(
        name="search_kb",
        description="Search the knowledge base for relevant information",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 5
                }
            },
            "required": ["query"]
        },
        handler=handler,
    )


def create_generate_image_tool(handler: Callable) -> ToolDefinition:
    """Create image generation tool."""
    return ToolDefinition(
        name="generate_image",
        description="Generate an AI image based on a text prompt",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Description of the image to generate"
                },
                "style": {
                    "type": "string",
                    "description": "Style of the image (e.g., 'photorealistic', 'illustration')",
                    "default": "photorealistic"
                }
            },
            "required": ["prompt"]
        },
        handler=handler,
        estimated_duration=10.0,
    )


def create_store_workspace_tool(handler: Callable) -> ToolDefinition:
    """Create workspace storage tool."""
    return ToolDefinition(
        name="store_in_workspace",
        description="Store large content in workspace for later reference",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name/identifier for the content"
                },
                "content": {
                    "type": "string",
                    "description": "Content to store"
                },
                "content_type": {
                    "type": "string",
                    "description": "Type of content (e.g., 'analysis', 'data', 'report')",
                    "default": "text"
                }
            },
            "required": ["name", "content"]
        },
        handler=handler,
    )
