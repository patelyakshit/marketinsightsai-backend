"""
Planner Agent

Decomposes complex tasks into executable steps.
Creates structured plans that can be tracked via the goal service.

Inspired by Manus AI's planning approach:
- Task decomposition
- Goal hierarchy
- Dependency management
- Progress tracking via todo.md pattern
"""

import json
import logging
from dataclasses import dataclass, field
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
)
from app.config import get_settings
settings = get_settings()

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    id: str
    description: str
    action_type: str  # "tool_call", "analysis", "generation", "verification"
    tool: Optional[str] = None
    params: dict = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)  # IDs of steps this depends on
    estimated_tokens: int = 0
    priority: int = 1


@dataclass
class ExecutionPlan:
    """A complete execution plan for a task."""
    task_summary: str
    steps: list[PlanStep]
    estimated_total_tokens: int
    estimated_tool_calls: int
    requires_verification: bool
    notes: str = ""


class PlannerAgent(BaseAgent):
    """
    Planner agent that decomposes tasks into executable steps.

    Responsibilities:
    1. Analyze task requirements
    2. Break down complex tasks into steps
    3. Identify tool requirements
    4. Create dependency graph
    5. Integrate with goal service for tracking
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        session_id: Optional[str] = None,
    ):
        config = AgentConfig(
            name="planner",
            role=AgentRole.PLANNER,
            model=settings.openai_model,
            temperature=0.4,
            max_tokens=2048,
            max_iterations=3,
        )
        super().__init__(config, db, session_id)

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    def get_system_prompt(self) -> str:
        return """You are the Planner agent for MarketInsightsAI.

Your role is to break down complex tasks into clear, executable steps.

## Available Tools

1. **geocode**: Convert address to coordinates
2. **get_tapestry**: Get Tapestry segment data for a location
3. **search_kb**: Search knowledge base for relevant information
4. **generate_image**: Create AI-generated images
5. **generate_report**: Generate PDF reports
6. **analyze_data**: Analyze uploaded data files

## Planning Guidelines

1. **Decompose Clearly**: Each step should be atomic and achievable
2. **Order Dependencies**: Steps that depend on others should be listed after
3. **Estimate Resources**: Consider token usage and tool calls
4. **Consider Verification**: Complex outputs need verification steps

## Output Format

Respond with a JSON object:
```json
{
  "task_summary": "Brief summary of what needs to be done",
  "steps": [
    {
      "id": "step_1",
      "description": "Clear description of this step",
      "action_type": "tool_call|analysis|generation|verification",
      "tool": "tool_name or null",
      "params": {"key": "value"},
      "dependencies": [],
      "priority": 1
    }
  ],
  "estimated_tokens": 5000,
  "estimated_tool_calls": 3,
  "requires_verification": true,
  "notes": "Any important considerations"
}
```

## Examples

### Simple Task (Generate marketing post)
```json
{
  "task_summary": "Generate marketing post for coffee shop",
  "steps": [
    {"id": "s1", "description": "Generate compelling copy", "action_type": "generation", "dependencies": []},
    {"id": "s2", "description": "Create supporting image", "action_type": "tool_call", "tool": "generate_image", "dependencies": ["s1"]}
  ],
  "estimated_tokens": 2000,
  "estimated_tool_calls": 1,
  "requires_verification": false
}
```

### Complex Task (Tapestry analysis)
```json
{
  "task_summary": "Analyze Tapestry data for multiple store locations",
  "steps": [
    {"id": "s1", "description": "Parse uploaded XLSX data", "action_type": "analysis", "dependencies": []},
    {"id": "s2", "description": "Geocode each location", "action_type": "tool_call", "tool": "geocode", "dependencies": ["s1"]},
    {"id": "s3", "description": "Get Tapestry segments", "action_type": "tool_call", "tool": "get_tapestry", "dependencies": ["s2"]},
    {"id": "s4", "description": "Generate comparative analysis", "action_type": "analysis", "dependencies": ["s3"]},
    {"id": "s5", "description": "Create PDF report", "action_type": "tool_call", "tool": "generate_report", "dependencies": ["s4"]},
    {"id": "s6", "description": "Verify report quality", "action_type": "verification", "dependencies": ["s5"]}
  ],
  "estimated_tokens": 15000,
  "estimated_tool_calls": 5,
  "requires_verification": true
}
```
"""

    async def create_plan(
        self,
        task: str,
        context: Optional[dict] = None
    ) -> ExecutionPlan:
        """
        Create an execution plan for a task.

        Args:
            task: Task description
            context: Additional context (classification, files, etc.)

        Returns:
            ExecutionPlan with steps
        """
        self.clear_messages()
        self.add_system_message(self.get_system_prompt())

        # Build context message
        context_str = ""
        if context:
            if "classification" in context:
                ctx = context["classification"]
                context_str += f"\nTask Type: {ctx.get('task_type', 'unknown')}"
                context_str += f"\nComplexity: {ctx.get('estimated_complexity', 'moderate')}"
                if ctx.get("entities"):
                    context_str += f"\nEntities: {json.dumps(ctx['entities'])}"

        self.add_user_message(f"Create an execution plan for:\n\n{task}{context_str}")

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

            # Parse steps
            steps = []
            for step_data in result.get("steps", []):
                steps.append(PlanStep(
                    id=step_data.get("id", f"step_{len(steps)}"),
                    description=step_data.get("description", ""),
                    action_type=step_data.get("action_type", "analysis"),
                    tool=step_data.get("tool"),
                    params=step_data.get("params", {}),
                    dependencies=step_data.get("dependencies", []),
                    priority=step_data.get("priority", 1),
                ))

            return ExecutionPlan(
                task_summary=result.get("task_summary", task[:100]),
                steps=steps,
                estimated_total_tokens=result.get("estimated_tokens", 5000),
                estimated_tool_calls=result.get("estimated_tool_calls", len(steps)),
                requires_verification=result.get("requires_verification", False),
                notes=result.get("notes", ""),
            )

        except Exception as e:
            logger.error(f"Plan creation error: {e}")
            # Return minimal fallback plan
            return ExecutionPlan(
                task_summary=task[:100],
                steps=[PlanStep(
                    id="fallback",
                    description="Execute task directly",
                    action_type="analysis",
                )],
                estimated_total_tokens=2000,
                estimated_tool_calls=0,
                requires_verification=False,
                notes=f"Fallback plan due to error: {e}",
            )

    async def execute(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Create a plan and optionally save goals to session.

        Args:
            task: Task description
            context: Additional context

        Returns:
            AgentResult with plan as output
        """
        self.start_time = utc_now()
        self.set_state(AgentState.PLANNING)
        self.iterations += 1

        try:
            # Create the plan
            plan = await self.create_plan(task, context)

            # Save goals to session if available
            if self.db and self.session_id:
                await self._save_goals_from_plan(plan)

            # Format plan as output
            output = self._format_plan_output(plan)

            self.set_state(AgentState.COMPLETE)

            return AgentResult(
                success=True,
                output=output,
                state=AgentState.COMPLETE,
                iterations=self.iterations,
                tokens_used=self.tokens_used,
                duration_ms=self.get_duration_ms(),
                metadata={
                    "plan": {
                        "task_summary": plan.task_summary,
                        "step_count": len(plan.steps),
                        "estimated_tokens": plan.estimated_total_tokens,
                        "estimated_tool_calls": plan.estimated_tool_calls,
                        "requires_verification": plan.requires_verification,
                    }
                },
                goals_created=[step.description for step in plan.steps],
            )

        except Exception as e:
            logger.error(f"Planner execution error: {e}")
            self.set_state(AgentState.ERROR)

            return AgentResult(
                success=False,
                output=f"Failed to create plan: {str(e)}",
                state=AgentState.ERROR,
                iterations=self.iterations,
                tokens_used=self.tokens_used,
                duration_ms=self.get_duration_ms(),
                error=str(e),
            )

    async def _save_goals_from_plan(self, plan: ExecutionPlan) -> None:
        """Save plan steps as goals in the session."""
        from app.services.context import add_goal

        parent_goal = await add_goal(
            db=self.db,
            session_id=self.session_id,
            goal_text=plan.task_summary,
            priority=1,
        )

        for i, step in enumerate(plan.steps):
            await add_goal(
                db=self.db,
                session_id=self.session_id,
                goal_text=step.description,
                parent_goal_id=parent_goal.id,
                priority=i + 1,
            )

    def _format_plan_output(self, plan: ExecutionPlan) -> str:
        """Format plan as readable output."""
        lines = [
            f"## Plan: {plan.task_summary}",
            "",
            "### Steps:",
        ]

        for i, step in enumerate(plan.steps, 1):
            deps = f" (depends on: {', '.join(step.dependencies)})" if step.dependencies else ""
            tool = f" [{step.tool}]" if step.tool else ""
            lines.append(f"{i}. {step.description}{tool}{deps}")

        lines.extend([
            "",
            "### Estimates:",
            f"- Tokens: ~{plan.estimated_total_tokens:,}",
            f"- Tool calls: {plan.estimated_tool_calls}",
            f"- Verification: {'Required' if plan.requires_verification else 'Not required'}",
        ])

        if plan.notes:
            lines.extend(["", f"### Notes:", plan.notes])

        return "\n".join(lines)
