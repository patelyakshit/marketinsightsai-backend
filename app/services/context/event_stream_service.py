"""
Event Stream Service

Handles chronological event logging for context persistence.
Implements append-only design for KV-cache optimization.
"""

import json
import uuid
import traceback
from typing import Optional, Any

from sqlalchemy import select, func

from app.utils.datetime_utils import utc_now
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionEvent, EventType, ChatSession
from app.services.context.token_service import count_tokens


async def get_next_sequence_num(
    db: AsyncSession,
    session_id: str
) -> int:
    """Get the next sequence number for a session."""
    result = await db.execute(
        select(func.max(SessionEvent.sequence_num))
        .where(SessionEvent.session_id == session_id)
    )
    max_seq = result.scalar()
    return (max_seq or 0) + 1


async def append_event(
    db: AsyncSession,
    session_id: str,
    event_type: EventType,
    content: dict | str,
    metadata: Optional[dict] = None,
    model: str = "gpt-4o"
) -> SessionEvent:
    """
    Append a new event to the session's event stream.

    This is the core function for the append-only event stream.
    Events are never modified or deleted (except during session cleanup).

    Args:
        db: Database session
        session_id: Session ID
        event_type: Type of event (user, assistant, action, observation, plan, error)
        content: Event content (dict or string)
        metadata: Optional additional metadata
        model: Model for token counting

    Returns:
        Created SessionEvent
    """
    # Convert content to JSON string if needed
    if isinstance(content, dict):
        content_str = json.dumps(content)
    else:
        content_str = content

    # Count tokens for this event
    token_count = count_tokens(content_str, model)

    # Get next sequence number
    sequence_num = await get_next_sequence_num(db, session_id)

    event = SessionEvent(
        id=str(uuid.uuid4()),
        session_id=session_id,
        sequence_num=sequence_num,
        event_type=event_type,
        content=content_str,
        token_count=token_count,
        cached_tokens=0,  # Will be updated based on actual API response
        event_metadata=metadata or {},
    )

    db.add(event)

    # Update session last activity
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session:
        session.last_activity_at = utc_now()

    await db.commit()
    await db.refresh(event)

    return event


async def record_user_message(
    db: AsyncSession,
    session_id: str,
    message: str,
    metadata: Optional[dict] = None
) -> SessionEvent:
    """
    Record a user message event.

    Args:
        db: Database session
        session_id: Session ID
        message: User's message text
        metadata: Optional metadata (e.g., file attachments)

    Returns:
        Created SessionEvent
    """
    return await append_event(
        db=db,
        session_id=session_id,
        event_type=EventType.user,
        content={"message": message},
        metadata=metadata,
    )


async def record_assistant_response(
    db: AsyncSession,
    session_id: str,
    response: str,
    sources: Optional[list[str]] = None,
    metadata: Optional[dict] = None
) -> SessionEvent:
    """
    Record an assistant (AI) response event.

    Args:
        db: Database session
        session_id: Session ID
        response: AI's response text
        sources: Optional list of sources used
        metadata: Optional metadata (e.g., model used, tokens)

    Returns:
        Created SessionEvent
    """
    content = {"response": response}
    if sources:
        content["sources"] = sources

    return await append_event(
        db=db,
        session_id=session_id,
        event_type=EventType.assistant,
        content=content,
        metadata=metadata,
    )


async def record_action(
    db: AsyncSession,
    session_id: str,
    action: str,
    tool: str,
    params: dict,
    metadata: Optional[dict] = None
) -> SessionEvent:
    """
    Record an action (tool call) event.

    Args:
        db: Database session
        session_id: Session ID
        action: Action description
        tool: Tool/function name being called
        params: Parameters passed to the tool

    Returns:
        Created SessionEvent
    """
    return await append_event(
        db=db,
        session_id=session_id,
        event_type=EventType.action,
        content={
            "action": action,
            "tool": tool,
            "params": params,
        },
        metadata=metadata,
    )


async def record_observation(
    db: AsyncSession,
    session_id: str,
    action_event_id: str,
    result: Any,
    error: Optional[str] = None,
    metadata: Optional[dict] = None
) -> SessionEvent:
    """
    Record an observation (result from action) event.

    Args:
        db: Database session
        session_id: Session ID
        action_event_id: ID of the action event this is responding to
        result: Result from the action
        error: Optional error message if action failed

    Returns:
        Created SessionEvent
    """
    content = {
        "action_event_id": action_event_id,
        "result": result,
    }

    if error:
        content["error"] = error

    return await append_event(
        db=db,
        session_id=session_id,
        event_type=EventType.observation,
        content=content,
        metadata=metadata,
    )


async def record_plan(
    db: AsyncSession,
    session_id: str,
    plan: str,
    goals: Optional[list[str]] = None,
    metadata: Optional[dict] = None
) -> SessionEvent:
    """
    Record a planning/reasoning step event.

    Args:
        db: Database session
        session_id: Session ID
        plan: Planning/reasoning text
        goals: Optional list of goals identified

    Returns:
        Created SessionEvent
    """
    content = {"plan": plan}
    if goals:
        content["goals"] = goals

    return await append_event(
        db=db,
        session_id=session_id,
        event_type=EventType.plan,
        content=content,
        metadata=metadata,
    )


async def record_error(
    db: AsyncSession,
    session_id: str,
    error: Exception | str,
    context: str,
    metadata: Optional[dict] = None
) -> SessionEvent:
    """
    Record an error event for model learning.

    Preserving error states helps the model adapt and avoid repeating mistakes.

    Args:
        db: Database session
        session_id: Session ID
        error: Exception or error message
        context: Context where error occurred

    Returns:
        Created SessionEvent
    """
    content = {
        "error": str(error),
        "context": context,
    }

    # Include traceback if it's an exception
    if isinstance(error, Exception):
        content["traceback"] = traceback.format_exc()
        content["error_type"] = type(error).__name__

    return await append_event(
        db=db,
        session_id=session_id,
        event_type=EventType.error,
        content=content,
        metadata=metadata,
    )


async def get_recent_events(
    db: AsyncSession,
    session_id: str,
    limit: int = 50,
    event_types: Optional[list[EventType]] = None
) -> list[SessionEvent]:
    """
    Get recent events for a session.

    Args:
        db: Database session
        session_id: Session ID
        limit: Maximum number of events to return
        event_types: Optional filter by event types

    Returns:
        List of SessionEvent (most recent first)
    """
    query = (
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.sequence_num.desc())
        .limit(limit)
    )

    if event_types:
        query = query.where(SessionEvent.event_type.in_(event_types))

    result = await db.execute(query)
    events = result.scalars().all()

    # Return in chronological order (oldest first)
    return list(reversed(events))


async def get_events(
    db: AsyncSession,
    session_id: str,
    limit: int = 50,
    offset: int = 0,
    event_types: Optional[list[EventType]] = None
) -> tuple[list[SessionEvent], int]:
    """
    Get events with pagination.

    Args:
        db: Database session
        session_id: Session ID
        limit: Max events per page
        offset: Pagination offset
        event_types: Optional filter

    Returns:
        Tuple of (events, total_count)
    """
    # Count query
    count_query = (
        select(func.count(SessionEvent.id))
        .where(SessionEvent.session_id == session_id)
    )

    if event_types:
        count_query = count_query.where(SessionEvent.event_type.in_(event_types))

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Events query
    query = (
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.sequence_num.asc())
        .limit(limit)
        .offset(offset)
    )

    if event_types:
        query = query.where(SessionEvent.event_type.in_(event_types))

    result = await db.execute(query)
    events = result.scalars().all()

    return list(events), total


async def get_conversation_messages(
    db: AsyncSession,
    session_id: str,
    limit: int = 50
) -> list[dict]:
    """
    Get conversation messages formatted for OpenAI API.

    Args:
        db: Database session
        session_id: Session ID
        limit: Maximum messages to include

    Returns:
        List of message dicts with 'role' and 'content' keys
    """
    events = await get_recent_events(
        db=db,
        session_id=session_id,
        limit=limit,
        event_types=[EventType.user, EventType.assistant],
    )

    messages = []
    for event in events:
        try:
            content = json.loads(event.content) if isinstance(event.content, str) else event.content

            if event.event_type == EventType.user:
                messages.append({
                    "role": "user",
                    "content": content.get("message", str(content)),
                })
            elif event.event_type == EventType.assistant:
                messages.append({
                    "role": "assistant",
                    "content": content.get("response", str(content)),
                })
        except (json.JSONDecodeError, AttributeError):
            # Handle raw string content
            role = "user" if event.event_type == EventType.user else "assistant"
            messages.append({
                "role": role,
                "content": str(event.content),
            })

    return messages


async def get_total_event_tokens(
    db: AsyncSession,
    session_id: str
) -> int:
    """
    Get total tokens used by all events in a session.

    Args:
        db: Database session
        session_id: Session ID

    Returns:
        Total token count
    """
    result = await db.execute(
        select(func.sum(SessionEvent.token_count))
        .where(SessionEvent.session_id == session_id)
    )
    return result.scalar() or 0


async def update_cached_tokens(
    db: AsyncSession,
    event_id: str,
    cached_tokens: int
) -> None:
    """
    Update the cached token count for an event.

    Called after receiving actual cache hit info from OpenAI.

    Args:
        db: Database session
        event_id: Event ID
        cached_tokens: Number of cached tokens
    """
    result = await db.execute(
        select(SessionEvent).where(SessionEvent.id == event_id)
    )
    event = result.scalar_one_or_none()

    if event:
        event.cached_tokens = cached_tokens
        await db.commit()
