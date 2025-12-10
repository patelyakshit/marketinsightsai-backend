"""
Orchestrator Agent

Routes tasks to appropriate specialized agents based on task analysis.
Coordinates multi-agent workflows and manages overall task execution.

Inspired by Manus AI's orchestration pattern:
- Task classification and routing
- Parallel agent coordination
- Result aggregation
- Error recovery
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.utils.datetime_utils import utc_now

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import (
    BaseAgent,
    AgentConfig,
    AgentResult,
    AgentRole,
    AgentState,
    MessageRole,
)
from app.config import get_settings
settings = get_settings()

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Types of tasks the system can handle."""
    CHAT = "chat"  # General conversation
    TAPESTRY = "tapestry"  # Tapestry report generation
    MARKETING = "marketing"  # Marketing content generation
    RESEARCH = "research"  # Deep research tasks
    ANALYSIS = "analysis"  # Data analysis
    SLIDES = "slides"  # Presentation generation
    GEOCODE = "geocode"  # Location/map operations
    UNKNOWN = "unknown"


@dataclass
class TaskClassification:
    """Result of task classification."""
    task_type: TaskType
    confidence: float
    requires_planning: bool
    estimated_complexity: str  # "simple", "moderate", "complex"
    suggested_agents: list[str]
    extracted_entities: dict  # Location, data references, etc.


class OrchestratorAgent(BaseAgent):
    """
    Orchestrator agent that routes tasks to specialized agents.

    Responsibilities:
    1. Classify incoming tasks
    2. Determine required agents
    3. Coordinate execution flow
    4. Aggregate results
    5. Handle errors and retries
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        session_id: Optional[str] = None,
    ):
        config = AgentConfig(
            name="orchestrator",
            role=AgentRole.ORCHESTRATOR,
            model=settings.openai_model,
            temperature=0.3,  # Lower temperature for classification
            max_tokens=1024,
            max_iterations=5,
        )
        super().__init__(config, db, session_id)

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.specialist_agents: dict[str, BaseAgent] = {}

    def get_system_prompt(self) -> str:
        return """You are the Orchestrator agent for MarketInsightsAI, a location intelligence platform.

Your role is to analyze user requests and determine the best way to handle them.

## Task Types

1. **CHAT**: General conversation, questions, explanations
2. **TAPESTRY**: Requests involving Esri Tapestry data, consumer segments, demographics
3. **MARKETING**: Creating marketing content, social media posts, campaign materials
4. **RESEARCH**: Deep research tasks requiring multiple sources
5. **ANALYSIS**: Data analysis, comparisons, insights generation
6. **SLIDES**: Creating presentations or slide decks
7. **GEOCODE**: Location lookups, map navigation, address parsing

## Classification Output

Respond with a JSON object:
```json
{
  "task_type": "chat|tapestry|marketing|research|analysis|slides|geocode",
  "confidence": 0.0-1.0,
  "requires_planning": true|false,
  "complexity": "simple|moderate|complex",
  "suggested_agents": ["planner", "executor", "verifier"],
  "entities": {
    "location": "extracted location if any",
    "data_source": "mentioned data files",
    "output_format": "pdf|pptx|image|text"
  },
  "reasoning": "Brief explanation of classification"
}
```

## Guidelines

- Tapestry requests mention: segments, demographics, LifeMode, consumer profiles, trade areas
- Marketing requests mention: posts, content, campaigns, ads, social media, images
- Research requests are open-ended questions requiring investigation
- Analysis requests involve comparing data, finding patterns, generating insights
- Be decisive - pick the most likely task type even if uncertain
"""

    async def classify_task(self, task: str) -> TaskClassification:
        """
        Classify an incoming task to determine routing.

        Args:
            task: User's task description

        Returns:
            TaskClassification with routing information
        """
        self.add_system_message(self.get_system_prompt())
        self.add_user_message(f"Classify this request:\n\n{task}")

        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=self.get_messages_for_api(),
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            self.tokens_used += response.usage.total_tokens

            return TaskClassification(
                task_type=TaskType(result.get("task_type", "unknown")),
                confidence=result.get("confidence", 0.5),
                requires_planning=result.get("requires_planning", False),
                estimated_complexity=result.get("complexity", "moderate"),
                suggested_agents=result.get("suggested_agents", ["executor"]),
                extracted_entities=result.get("entities", {}),
            )

        except Exception as e:
            logger.error(f"Task classification error: {e}")
            # Default to chat if classification fails
            return TaskClassification(
                task_type=TaskType.CHAT,
                confidence=0.5,
                requires_planning=False,
                estimated_complexity="simple",
                suggested_agents=["executor"],
                extracted_entities={},
            )

    def register_specialist(self, name: str, agent: BaseAgent) -> None:
        """Register a specialist agent."""
        self.specialist_agents[name] = agent
        logger.debug(f"Orchestrator registered specialist: {name}")

    async def execute(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Execute a task by routing to appropriate agents.

        Args:
            task: The user's request
            context: Optional additional context (files, session state, etc.)

        Returns:
            AgentResult with final output
        """
        self.start_time = utc_now()
        self.set_state(AgentState.PLANNING)

        try:
            # Step 1: Classify the task
            classification = await self.classify_task(task)
            logger.info(f"Task classified as: {classification.task_type.value} "
                       f"(confidence: {classification.confidence:.2f})")

            # Log classification to session
            if self.db and self.session_id:
                from app.services.context import record_plan
                await record_plan(
                    db=self.db,
                    session_id=self.session_id,
                    plan=f"Classified task as {classification.task_type.value}",
                    goals=[f"Execute {classification.task_type.value} task"],
                    metadata={"classification": classification.__dict__}
                )

            # Step 2: Route to appropriate handler
            self.set_state(AgentState.EXECUTING)

            if classification.requires_planning and "planner" in self.specialist_agents:
                # Complex task - use planner first
                result = await self._execute_with_planner(task, classification, context)
            else:
                # Simple task - route directly
                result = await self._route_to_specialist(task, classification, context)

            # Step 3: Verify result if verifier is available
            if "verifier" in self.specialist_agents and result.success:
                result = await self._verify_result(task, result)

            self.set_state(AgentState.COMPLETE)
            return result

        except Exception as e:
            logger.error(f"Orchestrator execution error: {e}")
            self.set_state(AgentState.ERROR)

            return AgentResult(
                success=False,
                output=f"I encountered an error while processing your request: {str(e)}",
                state=AgentState.ERROR,
                iterations=self.iterations,
                tool_calls_made=self.tool_calls_made,
                tokens_used=self.tokens_used,
                duration_ms=self.get_duration_ms(),
                error=str(e),
            )

    async def _execute_with_planner(
        self,
        task: str,
        classification: TaskClassification,
        context: Optional[dict]
    ) -> AgentResult:
        """Execute task using planner for complex tasks."""
        planner = self.specialist_agents.get("planner")
        if not planner:
            # Fallback to direct routing
            return await self._route_to_specialist(task, classification, context)

        # Plan the task
        plan_result = await planner.execute(task, {
            "classification": classification.__dict__,
            **(context or {}),
        })

        if not plan_result.success:
            return plan_result

        # Execute the plan
        executor = self.specialist_agents.get("executor")
        if executor:
            return await executor.execute(task, {
                "plan": plan_result.output,
                "classification": classification.__dict__,
                **(context or {}),
            })

        return plan_result

    async def _route_to_specialist(
        self,
        task: str,
        classification: TaskClassification,
        context: Optional[dict]
    ) -> AgentResult:
        """Route task to appropriate specialist agent."""
        # Map task types to specialist agents
        specialist_map = {
            TaskType.TAPESTRY: "tapestry_agent",
            TaskType.MARKETING: "marketing_agent",
            TaskType.RESEARCH: "research_agent",
            TaskType.SLIDES: "slides_agent",
            TaskType.ANALYSIS: "analysis_agent",
            TaskType.GEOCODE: "geocode_agent",
        }

        specialist_name = specialist_map.get(classification.task_type, "executor")
        specialist = self.specialist_agents.get(specialist_name)

        if not specialist:
            # Use default executor
            specialist = self.specialist_agents.get("executor")

        if specialist:
            return await specialist.execute(task, {
                "classification": classification.__dict__,
                **(context or {}),
            })

        # No specialist available - return simple response
        return AgentResult(
            success=True,
            output=f"Task type '{classification.task_type.value}' identified but no specialist agent available.",
            state=AgentState.COMPLETE,
            iterations=self.iterations,
            tokens_used=self.tokens_used,
            duration_ms=self.get_duration_ms(),
        )

    async def _verify_result(
        self,
        original_task: str,
        result: AgentResult
    ) -> AgentResult:
        """Verify result quality with verifier agent."""
        self.set_state(AgentState.VERIFYING)

        verifier = self.specialist_agents["verifier"]
        verification = await verifier.execute(
            f"Verify this response:\n\nOriginal task: {original_task}\n\nResponse: {result.output}",
            {"original_result": result.__dict__}
        )

        if verification.success:
            # Verifier approves or improves the result
            return AgentResult(
                success=True,
                output=verification.output if verification.output != result.output else result.output,
                state=AgentState.COMPLETE,
                iterations=self.iterations + verification.iterations,
                tool_calls_made=self.tool_calls_made + verification.tool_calls_made,
                tokens_used=self.tokens_used + verification.tokens_used,
                duration_ms=self.get_duration_ms(),
                metadata={**result.metadata, "verified": True},
            )

        return result  # Return original if verification fails
