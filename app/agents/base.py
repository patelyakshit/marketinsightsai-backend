"""
Base Agent Classes

Foundation for the multi-agent system inspired by Manus AI architecture.
Provides core abstractions for agent state, messaging, and tool execution.

Integrates with existing context services:
- event_stream_service: For recording agent actions
- context_builder_service: For managing conversation context
- goal_service: For tracking task progress
- workspace_service: For external memory
"""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from app.utils.datetime_utils import utc_now

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class AgentRole(str, Enum):
    """Agent roles in the multi-agent system."""
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    EXECUTOR = "executor"
    VERIFIER = "verifier"
    SPECIALIST = "specialist"


class AgentState(str, Enum):
    """Agent execution states."""
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"  # Waiting for tool response
    VERIFYING = "verifying"
    COMPLETE = "complete"
    ERROR = "error"


class MessageRole(str, Enum):
    """Message roles for agent communication."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class AgentConfig:
    """Configuration for an agent."""
    name: str
    role: AgentRole
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    max_iterations: int = 10  # Prevent infinite loops
    tools_enabled: bool = True
    parallel_tool_calls: bool = True

    # Context engineering settings
    context_window: int = 128000  # GPT-4o context window
    reserve_for_output: int = 4096
    max_history_events: int = 50

    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class AgentMessage:
    """A message in the agent conversation."""
    role: MessageRole
    content: str
    name: Optional[str] = None  # For tool responses
    tool_call_id: Optional[str] = None  # For tool responses
    tool_calls: Optional[list[dict]] = None  # For assistant tool calls
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict = field(default_factory=dict)

    def to_openai_format(self) -> dict:
        """Convert to OpenAI API message format."""
        msg = {
            "role": self.role.value,
            "content": self.content,
        }

        if self.name:
            msg["name"] = self.name
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls

        return msg


@dataclass
class ToolDefinition:
    """Definition of a tool available to agents."""
    name: str
    description: str
    parameters: dict  # JSON Schema for parameters
    handler: Optional[Callable] = None  # Async function to execute
    requires_confirmation: bool = False
    estimated_duration: float = 1.0  # Seconds

    def to_openai_format(self) -> dict:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


@dataclass
class ToolCall:
    """A tool call made by an agent."""
    id: str
    name: str
    arguments: dict
    timestamp: datetime = field(default_factory=utc_now)

    @classmethod
    def from_openai(cls, tool_call: dict) -> "ToolCall":
        """Create from OpenAI tool_call response."""
        return cls(
            id=tool_call["id"],
            name=tool_call["function"]["name"],
            arguments=json.loads(tool_call["function"]["arguments"]),
        )


@dataclass
class ToolResult:
    """Result from executing a tool."""
    tool_call_id: str
    name: str
    result: Any
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = 0
    timestamp: datetime = field(default_factory=utc_now)

    def to_message(self) -> AgentMessage:
        """Convert to agent message for context."""
        content = self.result if self.success else f"Error: {self.error}"
        if not isinstance(content, str):
            content = json.dumps(content)

        return AgentMessage(
            role=MessageRole.TOOL,
            content=content,
            name=self.name,
            tool_call_id=self.tool_call_id,
            metadata={
                "success": self.success,
                "duration_ms": self.duration_ms,
            }
        )


@dataclass
class AgentResult:
    """Result from agent execution."""
    success: bool
    output: str
    state: AgentState
    iterations: int = 0
    tool_calls_made: int = 0
    tokens_used: int = 0
    duration_ms: float = 0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    # Goals tracking
    goals_completed: list[str] = field(default_factory=list)
    goals_created: list[str] = field(default_factory=list)


# =============================================================================
# Base Agent Class
# =============================================================================

class BaseAgent(ABC):
    """
    Base class for all agents in the multi-agent system.

    Implements core functionality:
    - State management
    - Message history management
    - Tool registration and execution
    - Integration with context services
    - Event logging

    Subclasses should implement:
    - get_system_prompt(): Define agent's role and capabilities
    - execute(): Main execution logic
    """

    def __init__(
        self,
        config: AgentConfig,
        db: Optional[AsyncSession] = None,
        session_id: Optional[str] = None,
    ):
        self.id = str(uuid.uuid4())
        self.config = config
        self.db = db
        self.session_id = session_id

        # State
        self.state = AgentState.IDLE
        self.messages: list[AgentMessage] = []
        self.tools: dict[str, ToolDefinition] = {}

        # Metrics
        self.iterations = 0
        self.tool_calls_made = 0
        self.tokens_used = 0
        self.start_time: Optional[datetime] = None

    # -------------------------------------------------------------------------
    # Abstract Methods (must be implemented by subclasses)
    # -------------------------------------------------------------------------

    @abstractmethod
    def get_system_prompt(self) -> str:
        """
        Get the system prompt for this agent.

        Should define:
        - Agent's role and responsibilities
        - Available capabilities
        - Output format expectations
        - Constraints and guidelines
        """
        pass

    @abstractmethod
    async def execute(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Execute a task.

        Args:
            task: The task description or user request
            context: Optional additional context

        Returns:
            AgentResult with execution outcome
        """
        pass

    # -------------------------------------------------------------------------
    # Tool Management
    # -------------------------------------------------------------------------

    def register_tool(self, tool: ToolDefinition) -> None:
        """Register a tool for this agent to use."""
        self.tools[tool.name] = tool
        logger.debug(f"Agent {self.config.name} registered tool: {tool.name}")

    def register_tools(self, tools: list[ToolDefinition]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register_tool(tool)

    def get_tools_for_api(self) -> list[dict]:
        """Get all tools in OpenAI API format."""
        if not self.config.tools_enabled:
            return []
        return [tool.to_openai_format() for tool in self.tools.values()]

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute a tool call.

        Args:
            tool_call: The tool call to execute

        Returns:
            ToolResult with execution outcome
        """
        start_time = utc_now()

        tool = self.tools.get(tool_call.name)
        if not tool:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                success=False,
                error=f"Unknown tool: {tool_call.name}",
            )

        if not tool.handler:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                success=False,
                error=f"No handler registered for tool: {tool_call.name}",
            )

        try:
            # Execute the tool handler
            result = await tool.handler(**tool_call.arguments)

            duration_ms = (utc_now() - start_time).total_seconds() * 1000
            self.tool_calls_made += 1

            # Log action to event stream if session is active
            if self.db and self.session_id:
                await self._log_tool_execution(tool_call, result, None, duration_ms)

            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=result,
                success=True,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (utc_now() - start_time).total_seconds() * 1000
            error_msg = str(e)
            logger.error(f"Tool execution error: {tool_call.name} - {error_msg}")

            # Log error to event stream
            if self.db and self.session_id:
                await self._log_tool_execution(tool_call, None, error_msg, duration_ms)

            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=None,
                success=False,
                error=error_msg,
                duration_ms=duration_ms,
            )

    async def execute_parallel_tools(
        self,
        tool_calls: list[ToolCall]
    ) -> list[ToolResult]:
        """
        Execute multiple tool calls in parallel.

        Args:
            tool_calls: List of tool calls

        Returns:
            List of ToolResults in same order
        """
        import asyncio

        tasks = [self.execute_tool(tc) for tc in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(ToolResult(
                    tool_call_id=tool_calls[i].id,
                    name=tool_calls[i].name,
                    result=None,
                    success=False,
                    error=str(result),
                ))
            else:
                processed_results.append(result)

        return processed_results

    # -------------------------------------------------------------------------
    # Message Management
    # -------------------------------------------------------------------------

    def add_message(self, message: AgentMessage) -> None:
        """Add a message to the conversation history."""
        self.messages.append(message)

    def add_system_message(self, content: str) -> None:
        """Add a system message."""
        self.add_message(AgentMessage(role=MessageRole.SYSTEM, content=content))

    def add_user_message(self, content: str) -> None:
        """Add a user message."""
        self.add_message(AgentMessage(role=MessageRole.USER, content=content))

    def add_assistant_message(
        self,
        content: str,
        tool_calls: Optional[list[dict]] = None
    ) -> None:
        """Add an assistant message."""
        self.add_message(AgentMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        ))

    def get_messages_for_api(self) -> list[dict]:
        """Get all messages in OpenAI API format."""
        return [msg.to_openai_format() for msg in self.messages]

    def clear_messages(self) -> None:
        """Clear message history."""
        self.messages = []

    # -------------------------------------------------------------------------
    # State Management
    # -------------------------------------------------------------------------

    def set_state(self, state: AgentState) -> None:
        """Update agent state."""
        old_state = self.state
        self.state = state
        logger.debug(f"Agent {self.config.name} state: {old_state.value} -> {state.value}")

    def reset(self) -> None:
        """Reset agent to initial state."""
        self.state = AgentState.IDLE
        self.messages = []
        self.iterations = 0
        self.tool_calls_made = 0
        self.tokens_used = 0
        self.start_time = None

    # -------------------------------------------------------------------------
    # Context Integration
    # -------------------------------------------------------------------------

    async def load_session_context(self) -> None:
        """Load context from session if available."""
        if not self.db or not self.session_id:
            return

        from app.services.context import (
            build_messages_for_api,
            get_active_goals,
            format_goals_for_context,
        )

        # Load conversation history
        messages = await build_messages_for_api(
            db=self.db,
            session_id=self.session_id,
            max_events=self.config.max_history_events,
        )

        for msg in messages:
            self.add_message(AgentMessage(
                role=MessageRole(msg["role"]),
                content=msg["content"],
            ))

        # Load active goals
        goals = await get_active_goals(self.db, self.session_id)
        if goals:
            goals_text = await format_goals_for_context(self.db, self.session_id)
            if goals_text:
                # Append goals to system context (Manus pattern)
                self.add_system_message(f"\n\nCurrent Goals:\n{goals_text}")

    async def save_result_to_session(self, result: AgentResult) -> None:
        """Save agent result to session."""
        if not self.db or not self.session_id:
            return

        from app.services.context import record_assistant_response

        await record_assistant_response(
            db=self.db,
            session_id=self.session_id,
            response=result.output,
            metadata={
                "agent": self.config.name,
                "role": self.config.role.value,
                "iterations": result.iterations,
                "tool_calls": result.tool_calls_made,
                "tokens": result.tokens_used,
            }
        )

    # -------------------------------------------------------------------------
    # Event Logging
    # -------------------------------------------------------------------------

    async def _log_tool_execution(
        self,
        tool_call: ToolCall,
        result: Any,
        error: Optional[str],
        duration_ms: float
    ) -> None:
        """Log tool execution to event stream."""
        from app.services.context import record_action, record_observation

        # Record the action
        action_event = await record_action(
            db=self.db,
            session_id=self.session_id,
            action=f"Calling {tool_call.name}",
            tool=tool_call.name,
            params=tool_call.arguments,
            metadata={"agent": self.config.name}
        )

        # Record the observation
        await record_observation(
            db=self.db,
            session_id=self.session_id,
            action_event_id=action_event.id,
            result=result if not error else None,
            error=error,
            metadata={
                "duration_ms": duration_ms,
                "agent": self.config.name,
            }
        )

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_duration_ms(self) -> float:
        """Get execution duration in milliseconds."""
        if not self.start_time:
            return 0
        return (utc_now() - self.start_time).total_seconds() * 1000

    def should_stop(self) -> bool:
        """Check if agent should stop execution."""
        if self.iterations >= self.config.max_iterations:
            logger.warning(f"Agent {self.config.name} hit max iterations: {self.config.max_iterations}")
            return True
        return self.state in (AgentState.COMPLETE, AgentState.ERROR)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.config.name}, state={self.state.value})"
