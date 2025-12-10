"""
Token Service

Handles token counting, cost calculation, and usage tracking.
Uses tiktoken for accurate token counting with OpenAI models.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Optional

import tiktoken

from app.utils.datetime_utils import utc_now
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TokenUsage, ChatSession


# Pricing per 1 million tokens (as of Dec 2024)
PRICING: dict[str, dict[str, float]] = {
    # OpenAI GPT-4o
    "gpt-4o": {
        "input": 2.50,      # $2.50 per 1M input tokens
        "output": 10.00,    # $10.00 per 1M output tokens
        "cached": 1.25,     # $1.25 per 1M cached input tokens (50% discount)
    },
    "gpt-4o-2024-11-20": {
        "input": 2.50,
        "output": 10.00,
        "cached": 1.25,
    },
    "gpt-4o-2024-08-06": {
        "input": 2.50,
        "output": 10.00,
        "cached": 1.25,
    },
    # OpenAI GPT-4o mini
    "gpt-4o-mini": {
        "input": 0.15,      # $0.15 per 1M input tokens
        "output": 0.60,     # $0.60 per 1M output tokens
        "cached": 0.075,    # $0.075 per 1M cached tokens (50% discount)
    },
    "gpt-4o-mini-2024-07-18": {
        "input": 0.15,
        "output": 0.60,
        "cached": 0.075,
    },
    # OpenAI GPT-4 Turbo
    "gpt-4-turbo": {
        "input": 10.00,
        "output": 30.00,
        "cached": 5.00,
    },
    "gpt-4-turbo-preview": {
        "input": 10.00,
        "output": 30.00,
        "cached": 5.00,
    },
    # OpenAI GPT-3.5 Turbo
    "gpt-3.5-turbo": {
        "input": 0.50,
        "output": 1.50,
        "cached": 0.25,
    },
    # OpenAI Embeddings
    "text-embedding-3-small": {
        "input": 0.02,      # $0.02 per 1M tokens
        "output": 0.0,
        "cached": 0.0,
    },
    "text-embedding-3-large": {
        "input": 0.13,      # $0.13 per 1M tokens
        "output": 0.0,
        "cached": 0.0,
    },
    "text-embedding-ada-002": {
        "input": 0.10,
        "output": 0.0,
        "cached": 0.0,
    },
}

# Model to encoding mapping
MODEL_TO_ENCODING: dict[str, str] = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4o-2024-11-20": "o200k_base",
    "gpt-4o-2024-08-06": "o200k_base",
    "gpt-4o-mini-2024-07-18": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4-turbo-preview": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "text-embedding-3-small": "cl100k_base",
    "text-embedding-3-large": "cl100k_base",
    "text-embedding-ada-002": "cl100k_base",
}

# Cache for encodings
_encoding_cache: dict[str, tiktoken.Encoding] = {}


def _get_encoding(model: str) -> tiktoken.Encoding:
    """Get tiktoken encoding for a model, with caching."""
    encoding_name = MODEL_TO_ENCODING.get(model, "cl100k_base")

    if encoding_name not in _encoding_cache:
        _encoding_cache[encoding_name] = tiktoken.get_encoding(encoding_name)

    return _encoding_cache[encoding_name]


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """
    Count the number of tokens in a text string.

    Args:
        text: The text to count tokens for
        model: The model to use for tokenization (default: gpt-4o)

    Returns:
        Number of tokens in the text
    """
    if not text:
        return 0

    try:
        encoding = _get_encoding(model)
        return len(encoding.encode(text))
    except Exception:
        # Fallback: rough estimate (4 chars per token on average)
        return len(text) // 4


def count_messages_tokens(messages: list[dict], model: str = "gpt-4o") -> int:
    """
    Count tokens for a list of chat messages.

    Accounts for message formatting overhead used by OpenAI.

    Args:
        messages: List of message dicts with 'role' and 'content'
        model: The model to use for tokenization

    Returns:
        Total token count including formatting overhead
    """
    encoding = _get_encoding(model)

    # Token overhead per message (varies by model)
    tokens_per_message = 3  # <|start|>role<|end|>content<|end|>
    tokens_per_name = 1     # If name is present

    total_tokens = 0

    for message in messages:
        total_tokens += tokens_per_message
        for key, value in message.items():
            if isinstance(value, str):
                total_tokens += len(encoding.encode(value))
            if key == "name":
                total_tokens += tokens_per_name

    # Every reply is primed with <|start|>assistant<|message|>
    total_tokens += 3

    return total_tokens


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0
) -> float:
    """
    Calculate the cost in USD for an API call.

    Args:
        model: The model used
        input_tokens: Number of input tokens (including cached)
        output_tokens: Number of output tokens
        cached_tokens: Number of cached input tokens (for KV-cache)

    Returns:
        Cost in USD (as float for JSON serialization)
    """
    pricing = PRICING.get(model)

    if not pricing:
        # Try to find a matching base model
        for base_model, prices in PRICING.items():
            if model.startswith(base_model):
                pricing = prices
                break

    if not pricing:
        # Default to gpt-4o pricing if unknown
        pricing = PRICING["gpt-4o"]

    # Calculate cost (prices are per 1M tokens)
    uncached_input_tokens = input_tokens - cached_tokens

    input_cost = (uncached_input_tokens / 1_000_000) * pricing["input"]
    cached_cost = (cached_tokens / 1_000_000) * pricing["cached"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]

    return input_cost + cached_cost + output_cost


async def record_usage(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    request_type: str = "chat"
) -> TokenUsage:
    """
    Record token usage for a request.

    Args:
        db: Database session
        session_id: Chat session ID
        user_id: User ID
        model: Model used
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cached_tokens: Number of cached tokens
        request_type: Type of request (chat, embedding, image)

    Returns:
        Created TokenUsage record
    """
    cost = calculate_cost(model, input_tokens, output_tokens, cached_tokens)

    usage = TokenUsage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        user_id=user_id,
        model=model,
        request_type=request_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        cost_usd=Decimal(str(cost)),
    )

    db.add(usage)

    # Update session totals
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()

    if session:
        session.total_tokens_used = (session.total_tokens_used or 0) + input_tokens + output_tokens
        session.total_cost = Decimal(str(float(session.total_cost or 0) + cost))
        session.last_activity_at = utc_now()

    await db.commit()
    await db.refresh(usage)

    return usage


async def get_session_usage(
    db: AsyncSession,
    session_id: str
) -> dict:
    """
    Get aggregated usage statistics for a session.

    Args:
        db: Database session
        session_id: Chat session ID

    Returns:
        Dict with usage statistics
    """
    result = await db.execute(
        select(
            func.count(TokenUsage.id).label("total_requests"),
            func.sum(TokenUsage.input_tokens).label("total_input_tokens"),
            func.sum(TokenUsage.output_tokens).label("total_output_tokens"),
            func.sum(TokenUsage.cached_tokens).label("total_cached_tokens"),
            func.sum(TokenUsage.cost_usd).label("total_cost_usd"),
        ).where(TokenUsage.session_id == session_id)
    )

    row = result.one()

    total_input = row.total_input_tokens or 0
    total_cached = row.total_cached_tokens or 0

    # Calculate cache hit rate
    cache_hit_rate = 0.0
    if total_input > 0:
        cache_hit_rate = total_cached / total_input

    return {
        "session_id": session_id,
        "total_requests": row.total_requests or 0,
        "total_input_tokens": total_input,
        "total_output_tokens": row.total_output_tokens or 0,
        "total_cached_tokens": total_cached,
        "total_cost_usd": float(row.total_cost_usd or 0),
        "cache_hit_rate": cache_hit_rate,
    }


async def get_user_usage(
    db: AsyncSession,
    user_id: str,
    days: int = 30
) -> dict:
    """
    Get aggregated usage statistics for a user over a period.

    Args:
        db: Database session
        user_id: User ID
        days: Number of days to look back (default: 30)

    Returns:
        Dict with usage statistics
    """
    from datetime import timedelta

    cutoff = utc_now() - timedelta(days=days)

    result = await db.execute(
        select(
            func.count(TokenUsage.id).label("total_requests"),
            func.sum(TokenUsage.input_tokens).label("total_input_tokens"),
            func.sum(TokenUsage.output_tokens).label("total_output_tokens"),
            func.sum(TokenUsage.cached_tokens).label("total_cached_tokens"),
            func.sum(TokenUsage.cost_usd).label("total_cost_usd"),
        ).where(
            TokenUsage.user_id == user_id,
            TokenUsage.created_at >= cutoff
        )
    )

    row = result.one()

    total_input = row.total_input_tokens or 0
    total_cached = row.total_cached_tokens or 0

    cache_hit_rate = 0.0
    if total_input > 0:
        cache_hit_rate = total_cached / total_input

    return {
        "user_id": user_id,
        "period_days": days,
        "total_requests": row.total_requests or 0,
        "total_input_tokens": total_input,
        "total_output_tokens": row.total_output_tokens or 0,
        "total_cached_tokens": total_cached,
        "total_cost_usd": float(row.total_cost_usd or 0),
        "cache_hit_rate": cache_hit_rate,
    }


def estimate_context_tokens(
    system_prompt: str,
    conversation_history: list[dict],
    goals: str = "",
    model: str = "gpt-4o"
) -> dict:
    """
    Estimate token usage for a context window.

    Args:
        system_prompt: The system prompt
        conversation_history: List of conversation messages
        goals: Goals section (placed at end)
        model: Model for tokenization

    Returns:
        Dict with token breakdown and utilization metrics
    """
    # Model context limits
    context_limits = {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
    }

    max_tokens = context_limits.get(model, 128000)

    system_tokens = count_tokens(system_prompt, model)
    history_tokens = count_messages_tokens(conversation_history, model)
    goals_tokens = count_tokens(goals, model) if goals else 0

    total_tokens = system_tokens + history_tokens + goals_tokens
    available_tokens = max_tokens - total_tokens
    utilization = total_tokens / max_tokens

    return {
        "total_tokens": total_tokens,
        "system_tokens": system_tokens,
        "history_tokens": history_tokens,
        "goals_tokens": goals_tokens,
        "available_tokens": max(0, available_tokens),
        "max_tokens": max_tokens,
        "utilization": min(1.0, utilization),
        "cache_hit_estimate": 0.0,  # Will be updated based on actual usage
    }
