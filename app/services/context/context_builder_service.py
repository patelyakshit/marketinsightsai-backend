"""
Context Builder Service

Builds optimized context for AI calls with KV-cache optimization.
Implements Manus AI patterns:
1. Stable system prompt prefix (never changes)
2. Append-only event history
3. Goals at END of context (Todo.md recitation)
4. Compression for old events
"""

import json
from typing import Optional

from app.db.models import SessionEvent, SessionGoal, EventType, GoalStatus
from app.services.context.token_service import count_tokens, count_messages_tokens


# Context window limits by model
CONTEXT_LIMITS = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
}

# Reserve tokens for response
RESPONSE_RESERVE = 4000

# Budget allocation (percentages)
SYSTEM_PROMPT_BUDGET = 0.15  # 15% for system prompt
DOMAIN_CONTEXT_BUDGET = 0.15  # 15% for KB/Esri context
HISTORY_BUDGET = 0.55  # 55% for conversation history
GOALS_BUDGET = 0.10  # 10% for goals at end
BUFFER = 0.05  # 5% safety buffer


def get_stable_system_prompt() -> str:
    """
    Return the stable system prompt that NEVER CHANGES.

    This is critical for KV-cache optimization. The system prompt
    must be identical across requests to maximize cache hits.

    DO NOT add timestamps, dynamic content, or user-specific data here.
    Those go in domain_context or events.
    """
    return """You are MarketInsightsAI, an expert AI assistant specializing in location intelligence, consumer segmentation, and marketing strategy.

## Your Capabilities
- Analyze Esri Tapestry consumer segmentation data
- Generate marketing insights and recommendations
- Create targeted marketing content for different platforms
- Help with location-based decision making
- Answer questions about demographics and consumer behavior

## Your Personality
- Knowledgeable and data-driven
- Friendly but professional
- Proactive in offering relevant insights
- Clear and concise in explanations

## Response Guidelines
1. When analyzing segment data, highlight key insights first
2. Provide actionable recommendations when appropriate
3. Use specific data points to support your analysis
4. If generating marketing content, tailor it to the target audience
5. Acknowledge when you need more information to provide accurate answers

## Available Tools
You have access to tools for:
- Geocoding and location search
- Tapestry segment analysis
- Report generation
- Marketing content creation
- Image generation for marketing posts"""


def format_event_for_context(
    event: SessionEvent,
    compress: bool = False,
    model: str = "gpt-4o"
) -> str:
    """
    Format a single event for inclusion in context.

    Args:
        event: The event to format
        compress: If True, create a shorter summary
        model: Model for token counting

    Returns:
        Formatted event string
    """
    try:
        content = json.loads(event.content) if isinstance(event.content, str) else event.content
    except (json.JSONDecodeError, TypeError):
        content = {"text": str(event.content)}

    if event.event_type == EventType.user:
        message = content.get("message", str(content))
        if compress and len(message) > 200:
            message = message[:200] + "..."
        return f"User: {message}"

    elif event.event_type == EventType.assistant:
        response = content.get("response", str(content))
        if compress and len(response) > 300:
            response = response[:300] + "..."
        return f"Assistant: {response}"

    elif event.event_type == EventType.action:
        tool = content.get("tool", "unknown")
        action = content.get("action", "")
        if compress:
            return f"[Action: {tool}]"
        return f"[Action: {tool} - {action}]"

    elif event.event_type == EventType.observation:
        result = content.get("result", "")
        error = content.get("error")
        if error:
            if compress:
                return f"[Result: Error - {error[:50]}...]"
            return f"[Result: Error - {error}]"
        if compress:
            result_str = str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
            return f"[Result: {result_str}]"
        return f"[Result: {result}]"

    elif event.event_type == EventType.plan:
        plan = content.get("plan", str(content))
        if compress:
            return f"[Plan: {plan[:100]}...]"
        return f"[Plan: {plan}]"

    elif event.event_type == EventType.error:
        error = content.get("error", str(content))
        context_info = content.get("context", "")
        if compress:
            return f"[Error in {context_info}: {error[:50]}...]"
        return f"[Error in {context_info}: {error}]"

    return str(content)


def compress_old_events(
    events: list[SessionEvent],
    keep_recent: int = 20,
    model: str = "gpt-4o"
) -> list[dict]:
    """
    Compress old events to save tokens while keeping recent ones intact.

    Args:
        events: List of events (chronological order)
        keep_recent: Number of recent events to keep uncompressed
        model: Model for token counting

    Returns:
        List of formatted event dicts
    """
    if len(events) <= keep_recent:
        # All events are recent, no compression needed
        return [
            {"text": format_event_for_context(e, compress=False), "compressed": False}
            for e in events
        ]

    result = []

    # Old events (compress)
    old_events = events[:-keep_recent]
    for event in old_events:
        result.append({
            "text": format_event_for_context(event, compress=True),
            "compressed": True,
        })

    # Recent events (keep full)
    recent_events = events[-keep_recent:]
    for event in recent_events:
        result.append({
            "text": format_event_for_context(event, compress=False),
            "compressed": False,
        })

    return result


def format_goals_section(goals: list[SessionGoal]) -> str:
    """
    Format goals as a markdown todo list.

    Goals are placed at the END of context to combat "lost-in-the-middle" effect.
    This is the "Todo.md recitation" technique from Manus AI.

    Args:
        goals: List of session goals

    Returns:
        Formatted goals section
    """
    if not goals:
        return ""

    lines = ["## Current Objectives"]

    # Group by status
    in_progress = [g for g in goals if g.status == GoalStatus.in_progress]
    pending = [g for g in goals if g.status == GoalStatus.pending]
    completed = [g for g in goals if g.status == GoalStatus.completed]

    # In progress first (most important)
    for goal in in_progress:
        lines.append(f"- [ ] **{goal.goal_text}** (in progress)")

    # Pending
    for goal in pending:
        lines.append(f"- [ ] {goal.goal_text}")

    # Recently completed (last 3 only, for context)
    for goal in completed[-3:]:
        lines.append(f"- [x] ~~{goal.goal_text}~~ (done)")

    return "\n".join(lines)


def build_context(
    system_prompt: Optional[str] = None,
    domain_context: str = "",
    events: list[SessionEvent] = None,
    goals: list[SessionGoal] = None,
    workspace_refs: list[str] = None,
    max_tokens: Optional[int] = None,
    model: str = "gpt-4o"
) -> tuple[str, dict]:
    """
    Build the complete context window with KV-cache optimization.

    Structure (for cache stability):
    1. [STABLE SYSTEM PROMPT]     <- Never changes (cache hit)
    2. [DOMAIN CONTEXT]           <- Changes rarely (segments, KB)
    3. [WORKSPACE REFERENCES]     <- File references
    4. [SESSION EVENTS]           <- Append-only history
    5. [CURRENT GOALS]            <- At END for recency

    Args:
        system_prompt: Override system prompt (use stable default if None)
        domain_context: Domain-specific context (segments, KB results)
        events: Session events (conversation history)
        goals: Session goals
        workspace_refs: References to workspace files
        max_tokens: Max context tokens (defaults to model limit)
        model: Model being used

    Returns:
        Tuple of (context_string, metrics_dict)
    """
    events = events or []
    goals = goals or []
    workspace_refs = workspace_refs or []

    # Get limits
    context_limit = max_tokens or CONTEXT_LIMITS.get(model, 128000)
    available_tokens = context_limit - RESPONSE_RESERVE

    # Use stable system prompt by default
    final_system_prompt = system_prompt or get_stable_system_prompt()

    # Calculate budget
    system_budget = int(available_tokens * SYSTEM_PROMPT_BUDGET)
    domain_budget = int(available_tokens * DOMAIN_CONTEXT_BUDGET)
    history_budget = int(available_tokens * HISTORY_BUDGET)
    goals_budget = int(available_tokens * GOALS_BUDGET)

    # Build sections
    sections = []

    # 1. System prompt (stable prefix)
    system_tokens = count_tokens(final_system_prompt, model)
    sections.append(final_system_prompt)

    # 2. Domain context (if any)
    domain_tokens = 0
    if domain_context:
        domain_tokens = count_tokens(domain_context, model)
        if domain_tokens <= domain_budget:
            sections.append(f"\n## Context\n{domain_context}")
        else:
            # Truncate domain context if too long
            truncated = domain_context[:int(domain_budget * 4)]  # Rough char estimate
            sections.append(f"\n## Context\n{truncated}...")
            domain_tokens = domain_budget

    # 3. Workspace references
    workspace_tokens = 0
    if workspace_refs:
        workspace_section = "\n## Available Files\n" + "\n".join(f"- {ref}" for ref in workspace_refs)
        workspace_tokens = count_tokens(workspace_section, model)
        sections.append(workspace_section)

    # 4. Conversation history (append-only)
    history_tokens = 0
    if events:
        # Calculate how many events we can fit
        compressed_events = compress_old_events(events, keep_recent=20, model=model)

        history_lines = ["\n## Conversation History"]
        current_tokens = count_tokens("\n## Conversation History", model)

        for event_data in compressed_events:
            event_tokens = count_tokens(event_data["text"], model)
            if current_tokens + event_tokens > history_budget:
                # Stop adding events
                break
            history_lines.append(event_data["text"])
            current_tokens += event_tokens

        if len(history_lines) > 1:
            history_section = "\n".join(history_lines)
            history_tokens = count_tokens(history_section, model)
            sections.append(history_section)

    # 5. Goals at END (recency bias)
    goals_tokens = 0
    if goals:
        goals_section = "\n" + format_goals_section(goals)
        goals_tokens = count_tokens(goals_section, model)
        if goals_tokens <= goals_budget:
            sections.append(goals_section)
        else:
            # Keep only most important goals
            important_goals = [g for g in goals if g.status in [GoalStatus.in_progress, GoalStatus.pending]][:5]
            goals_section = "\n" + format_goals_section(important_goals)
            goals_tokens = count_tokens(goals_section, model)
            sections.append(goals_section)

    # Combine all sections
    full_context = "\n".join(sections)
    total_tokens = count_tokens(full_context, model)

    # Calculate metrics
    metrics = {
        "total_tokens": total_tokens,
        "system_tokens": system_tokens,
        "domain_tokens": domain_tokens,
        "workspace_tokens": workspace_tokens,
        "history_tokens": history_tokens,
        "goals_tokens": goals_tokens,
        "available_tokens": available_tokens - total_tokens,
        "max_tokens": context_limit,
        "utilization": total_tokens / context_limit,
        "cache_hit_estimate": system_tokens / total_tokens if total_tokens > 0 else 0,
    }

    return full_context, metrics


def build_messages_for_api(
    context: str,
    user_message: str,
    model: str = "gpt-4o"
) -> list[dict]:
    """
    Build the messages array for OpenAI API call.

    Args:
        context: The built context (system prompt + history + goals)
        user_message: The current user message

    Returns:
        List of message dicts for OpenAI API
    """
    return [
        {"role": "system", "content": context},
        {"role": "user", "content": user_message},
    ]


def estimate_cache_savings(
    system_tokens: int,
    total_tokens: int,
    model: str = "gpt-4o"
) -> dict:
    """
    Estimate potential cost savings from KV-cache hits.

    Args:
        system_tokens: Tokens in the stable prefix
        total_tokens: Total input tokens
        model: Model being used

    Returns:
        Dict with cost estimates
    """
    from app.services.context.token_service import PRICING

    pricing = PRICING.get(model, PRICING["gpt-4o"])

    # Calculate costs
    # Without caching: all tokens at input price
    uncached_cost = (total_tokens / 1_000_000) * pricing["input"]

    # With caching: system tokens at cached price, rest at input price
    cached_cost = (
        (system_tokens / 1_000_000) * pricing["cached"] +
        ((total_tokens - system_tokens) / 1_000_000) * pricing["input"]
    )

    savings = uncached_cost - cached_cost
    savings_percent = (savings / uncached_cost * 100) if uncached_cost > 0 else 0

    return {
        "uncached_cost_per_request": uncached_cost,
        "cached_cost_per_request": cached_cost,
        "savings_per_request": savings,
        "savings_percent": savings_percent,
        "system_tokens": system_tokens,
        "total_tokens": total_tokens,
    }
