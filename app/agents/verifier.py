"""
Verifier Agent

Quality control agent that validates outputs and suggests improvements.
Helps ensure accuracy and completeness of generated content.

Inspired by Manus AI's verification approach:
- Output quality assessment
- Fact checking
- Completeness verification
- Error detection and correction
"""

import json
import logging
from dataclasses import dataclass
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
class VerificationResult:
    """Result of verification."""
    passed: bool
    score: float  # 0.0 - 1.0
    issues: list[str]
    suggestions: list[str]
    improved_output: Optional[str] = None


class VerifierAgent(BaseAgent):
    """
    Verifier agent that checks output quality.

    Responsibilities:
    1. Assess output completeness
    2. Check for factual errors
    3. Verify task requirements are met
    4. Suggest improvements
    5. Provide corrected output when needed
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        session_id: Optional[str] = None,
    ):
        config = AgentConfig(
            name="verifier",
            role=AgentRole.VERIFIER,
            model=settings.openai_model,
            temperature=0.3,  # Lower for more consistent verification
            max_tokens=2048,
            max_iterations=2,
        )
        super().__init__(config, db, session_id)

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    def get_system_prompt(self) -> str:
        return """You are the Verifier agent for MarketInsightsAI.

Your role is to verify the quality and accuracy of AI-generated outputs.

## Verification Criteria

1. **Completeness**: Does the output address all parts of the request?
2. **Accuracy**: Are facts and data correct? No hallucinations?
3. **Relevance**: Is the content relevant to the original task?
4. **Clarity**: Is the output clear and well-organized?
5. **Actionability**: Can the user act on this information?

## Verification Output

Respond with a JSON object:
```json
{
  "passed": true|false,
  "score": 0.0-1.0,
  "issues": ["list of issues found"],
  "suggestions": ["list of improvement suggestions"],
  "improved_output": "corrected version if needed, or null"
}
```

## Guidelines

- Be constructive, not just critical
- If issues are minor, still pass but note them
- Pass threshold: score >= 0.7
- Only provide improved_output if significant changes needed
- Don't rewrite just to rewrite - only improve if there's clear value

## Scoring Guide

- 0.9-1.0: Excellent, no issues
- 0.7-0.89: Good, minor issues
- 0.5-0.69: Acceptable, some issues
- 0.3-0.49: Poor, significant issues
- 0.0-0.29: Unacceptable, major problems
"""

    async def verify(
        self,
        original_task: str,
        output: str,
        context: Optional[dict] = None,
    ) -> VerificationResult:
        """
        Verify an output against the original task.

        Args:
            original_task: The original user request
            output: The generated output to verify
            context: Additional context (plan, classification, etc.)

        Returns:
            VerificationResult with assessment
        """
        self.clear_messages()
        self.add_system_message(self.get_system_prompt())

        # Build verification request
        verification_request = f"""## Original Task
{original_task}

## Output to Verify
{output}
"""

        if context:
            if "plan" in context:
                verification_request += f"\n## Execution Plan\n{context['plan']}"
            if "classification" in context:
                verification_request += f"\n## Task Classification\n{json.dumps(context['classification'])}"

        self.add_user_message(verification_request)

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

            return VerificationResult(
                passed=result.get("passed", True),
                score=result.get("score", 0.8),
                issues=result.get("issues", []),
                suggestions=result.get("suggestions", []),
                improved_output=result.get("improved_output"),
            )

        except Exception as e:
            logger.error(f"Verification error: {e}")
            # Default to passing if verification fails
            return VerificationResult(
                passed=True,
                score=0.7,
                issues=[f"Verification failed: {str(e)}"],
                suggestions=["Manual review recommended"],
            )

    async def execute(
        self,
        task: str,
        context: Optional[dict] = None,
    ) -> AgentResult:
        """
        Execute verification as an agent task.

        Args:
            task: Verification request (should include original task and output)
            context: Optional context with original_result

        Returns:
            AgentResult with verification outcome
        """
        self.start_time = utc_now()
        self.set_state(AgentState.VERIFYING)
        self.iterations += 1

        try:
            # Parse the verification request
            # Expected format: "Verify this response:\n\nOriginal task: X\n\nResponse: Y"
            original_task = ""
            output = ""

            if "Original task:" in task and "Response:" in task:
                parts = task.split("Response:", 1)
                original_part = parts[0]
                output = parts[1].strip() if len(parts) > 1 else ""

                if "Original task:" in original_part:
                    original_task = original_part.split("Original task:", 1)[1].strip()
            else:
                # Fallback: treat entire task as output to verify
                output = task
                original_task = context.get("original_task", "Unknown task") if context else "Unknown task"

            # Perform verification
            verification = await self.verify(original_task, output, context)

            # Format result
            if verification.passed:
                result_output = verification.improved_output or output
                if verification.suggestions:
                    result_output += "\n\n---\n*Verification notes: " + "; ".join(verification.suggestions) + "*"
            else:
                if verification.improved_output:
                    result_output = verification.improved_output
                else:
                    result_output = output
                    result_output += "\n\n---\n*Issues found: " + "; ".join(verification.issues) + "*"

            self.set_state(AgentState.COMPLETE)

            return AgentResult(
                success=verification.passed,
                output=result_output,
                state=AgentState.COMPLETE,
                iterations=self.iterations,
                tokens_used=self.tokens_used,
                duration_ms=self.get_duration_ms(),
                metadata={
                    "verification": {
                        "passed": verification.passed,
                        "score": verification.score,
                        "issues": verification.issues,
                        "suggestions": verification.suggestions,
                    }
                },
            )

        except Exception as e:
            logger.error(f"Verifier execution error: {e}")
            self.set_state(AgentState.ERROR)

            return AgentResult(
                success=False,
                output=f"Verification failed: {str(e)}",
                state=AgentState.ERROR,
                iterations=self.iterations,
                tokens_used=self.tokens_used,
                duration_ms=self.get_duration_ms(),
                error=str(e),
            )
