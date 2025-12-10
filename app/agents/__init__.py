"""
Multi-Agent System for MarketInsightsAI

Manus AI-inspired architecture with specialized agents:
- BaseAgent: Foundation class for all agents
- OrchestratorAgent: Routes tasks to appropriate specialists
- PlannerAgent: Decomposes complex tasks into steps
- ExecutorAgent: Executes tool calls and actions
- VerifierAgent: Quality control and error recovery

Integrates with existing context services:
- event_stream_service: Event logging
- context_builder_service: Context management
- goal_service: Task tracking
- workspace_service: External memory
"""

from app.agents.base import (
    BaseAgent,
    AgentState,
    AgentRole,
    AgentMessage,
    AgentResult,
    AgentConfig,
    MessageRole,
    ToolDefinition,
    ToolCall,
    ToolResult,
)

from app.agents.orchestrator import (
    OrchestratorAgent,
    TaskType,
    TaskClassification,
)

from app.agents.planner import (
    PlannerAgent,
    PlanStep,
    ExecutionPlan,
)

from app.agents.executor import (
    ExecutorAgent,
    ExecutionStep,
    create_geocode_tool,
    create_get_tapestry_tool,
    create_search_kb_tool,
    create_generate_image_tool,
    create_store_workspace_tool,
)

from app.agents.verifier import (
    VerifierAgent,
    VerificationResult,
)

__all__ = [
    # Base classes
    "BaseAgent",
    "AgentState",
    "AgentRole",
    "AgentMessage",
    "AgentResult",
    "AgentConfig",
    "MessageRole",
    "ToolDefinition",
    "ToolCall",
    "ToolResult",

    # Orchestrator
    "OrchestratorAgent",
    "TaskType",
    "TaskClassification",

    # Planner
    "PlannerAgent",
    "PlanStep",
    "ExecutionPlan",

    # Executor
    "ExecutorAgent",
    "ExecutionStep",
    "create_geocode_tool",
    "create_get_tapestry_tool",
    "create_search_kb_tool",
    "create_generate_image_tool",
    "create_store_workspace_tool",

    # Verifier
    "VerifierAgent",
    "VerificationResult",
]
