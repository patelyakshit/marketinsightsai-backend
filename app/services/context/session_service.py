"""
Session Service

Manages chat session lifecycle: creation, retrieval, state persistence, and cleanup.
Sessions are tied to authenticated users and optionally to folders.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    ChatSession, SessionStateCache, SessionStatus,
    SessionEvent, SessionGoal, SessionWorkspaceFile, TokenUsage
)
from app.models.schemas import SessionState, Store, MapLocation, MarketingRecommendation


# Default session TTL (7 days)
DEFAULT_SESSION_TTL_DAYS = 7


async def create_session(
    db: AsyncSession,
    user_id: str,
    folder_id: Optional[str] = None,
    title: Optional[str] = None,
    ttl_days: int = DEFAULT_SESSION_TTL_DAYS
) -> ChatSession:
    """
    Create a new chat session.

    Args:
        db: Database session
        user_id: User ID (required)
        folder_id: Optional folder to bind session to
        title: Optional session title
        ttl_days: Days until session expires

    Returns:
        Created ChatSession
    """
    session_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(days=ttl_days)

    session = ChatSession(
        id=session_id,
        user_id=user_id,
        folder_id=folder_id,
        title=title,
        status=SessionStatus.active,
        expires_at=expires_at,
        context_window_used=0,
        total_tokens_used=0,
        total_cost=Decimal("0"),
    )

    db.add(session)

    # Create empty state cache for the session
    state_cache = SessionStateCache(
        id=str(uuid.uuid4()),
        session_id=session_id,
        pending_stores={},
        pending_disambiguation=[],
        pending_marketing=None,
        pending_report=None,
        last_location=None,
        active_segments=[],
    )

    db.add(state_cache)

    await db.commit()
    await db.refresh(session)

    return session


async def get_session(
    db: AsyncSession,
    session_id: str,
    user_id: Optional[str] = None
) -> Optional[ChatSession]:
    """
    Get a session by ID, optionally validating user ownership.

    Args:
        db: Database session
        session_id: Session ID to retrieve
        user_id: Optional user ID to validate ownership

    Returns:
        ChatSession or None if not found
    """
    query = select(ChatSession).where(ChatSession.id == session_id)

    if user_id:
        query = query.where(ChatSession.user_id == user_id)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_session_with_relations(
    db: AsyncSession,
    session_id: str,
    user_id: Optional[str] = None
) -> Optional[ChatSession]:
    """
    Get a session with all related data loaded.

    Args:
        db: Database session
        session_id: Session ID to retrieve
        user_id: Optional user ID to validate ownership

    Returns:
        ChatSession with events, goals, workspace_files, state_cache loaded
    """
    query = (
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .options(
            selectinload(ChatSession.events),
            selectinload(ChatSession.goals),
            selectinload(ChatSession.workspace_files),
            selectinload(ChatSession.state_cache),
        )
    )

    if user_id:
        query = query.where(ChatSession.user_id == user_id)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_or_create_session(
    db: AsyncSession,
    user_id: str,
    session_id: Optional[str] = None,
    folder_id: Optional[str] = None
) -> ChatSession:
    """
    Get an existing session or create a new one.

    Args:
        db: Database session
        user_id: User ID
        session_id: Optional existing session ID
        folder_id: Optional folder ID for new sessions

    Returns:
        ChatSession (existing or newly created)
    """
    if session_id:
        session = await get_session(db, session_id, user_id)
        if session and session.status == SessionStatus.active:
            # Update last activity
            session.last_activity_at = datetime.utcnow()
            await db.commit()
            return session

    # Create new session
    return await create_session(db, user_id, folder_id)


async def list_user_sessions(
    db: AsyncSession,
    user_id: str,
    status: Optional[SessionStatus] = None,
    limit: int = 50,
    offset: int = 0
) -> tuple[list[ChatSession], int]:
    """
    List sessions for a user.

    Args:
        db: Database session
        user_id: User ID
        status: Optional status filter
        limit: Max results
        offset: Pagination offset

    Returns:
        Tuple of (sessions list, total count)
    """
    from sqlalchemy import func

    # Base query
    query = select(ChatSession).where(ChatSession.user_id == user_id)
    count_query = select(func.count(ChatSession.id)).where(ChatSession.user_id == user_id)

    if status:
        query = query.where(ChatSession.status == status)
        count_query = count_query.where(ChatSession.status == status)

    # Get total count
    count_result = await db.execute(count_query)
    total = count_result.scalar()

    # Get sessions
    query = query.order_by(ChatSession.last_activity_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    sessions = result.scalars().all()

    return list(sessions), total


async def restore_session_state(
    db: AsyncSession,
    session: ChatSession
) -> SessionState:
    """
    Restore in-memory state from database cache.

    Args:
        db: Database session
        session: Chat session

    Returns:
        SessionState with restored data
    """
    # Get or create state cache
    result = await db.execute(
        select(SessionStateCache).where(SessionStateCache.session_id == session.id)
    )
    cache = result.scalar_one_or_none()

    if not cache:
        # Create empty cache
        cache = SessionStateCache(
            id=str(uuid.uuid4()),
            session_id=session.id,
            pending_stores={},
            pending_disambiguation=[],
            pending_marketing=None,
            pending_report=None,
            last_location=None,
            active_segments=[],
        )
        db.add(cache)
        await db.commit()
        await db.refresh(cache)

    # Convert JSON to typed objects
    pending_stores = {}
    if cache.pending_stores:
        for key, store_data in cache.pending_stores.items():
            try:
                pending_stores[key] = Store(**store_data)
            except Exception:
                pass

    pending_disambiguation = []
    if cache.pending_disambiguation:
        for loc_data in cache.pending_disambiguation:
            try:
                pending_disambiguation.append(MapLocation(**loc_data))
            except Exception:
                pass

    pending_marketing = None
    if cache.pending_marketing:
        try:
            pending_marketing = MarketingRecommendation(**cache.pending_marketing)
        except Exception:
            pass

    last_location = None
    if cache.last_location:
        try:
            last_location = MapLocation(**cache.last_location)
        except Exception:
            pass

    return SessionState(
        pending_stores=pending_stores,
        pending_disambiguation=pending_disambiguation,
        pending_marketing=pending_marketing,
        pending_report=cache.pending_report,
        last_location=last_location,
        active_segments=cache.active_segments or [],
    )


async def save_session_state(
    db: AsyncSession,
    session_id: str,
    state: SessionState
) -> None:
    """
    Persist session state to database for crash recovery.

    Args:
        db: Database session
        session_id: Session ID
        state: Current session state
    """
    # Convert typed objects to JSON-serializable dicts
    pending_stores_json = {}
    for key, store in state.pending_stores.items():
        pending_stores_json[key] = store.model_dump(by_alias=True)

    pending_disambiguation_json = [
        loc.model_dump(by_alias=True) for loc in state.pending_disambiguation
    ]

    pending_marketing_json = None
    if state.pending_marketing:
        pending_marketing_json = state.pending_marketing.model_dump(by_alias=True)

    last_location_json = None
    if state.last_location:
        last_location_json = state.last_location.model_dump(by_alias=True)

    # Update or create cache
    result = await db.execute(
        select(SessionStateCache).where(SessionStateCache.session_id == session_id)
    )
    cache = result.scalar_one_or_none()

    if cache:
        cache.pending_stores = pending_stores_json
        cache.pending_disambiguation = pending_disambiguation_json
        cache.pending_marketing = pending_marketing_json
        cache.pending_report = state.pending_report
        cache.last_location = last_location_json
        cache.active_segments = state.active_segments
        cache.updated_at = datetime.utcnow()
    else:
        cache = SessionStateCache(
            id=str(uuid.uuid4()),
            session_id=session_id,
            pending_stores=pending_stores_json,
            pending_disambiguation=pending_disambiguation_json,
            pending_marketing=pending_marketing_json,
            pending_report=state.pending_report,
            last_location=last_location_json,
            active_segments=state.active_segments,
        )
        db.add(cache)

    await db.commit()


async def update_session_metrics(
    db: AsyncSession,
    session_id: str,
    context_window_used: Optional[int] = None,
    tokens_used: Optional[int] = None,
    cost: Optional[float] = None
) -> None:
    """
    Update session metrics after an AI call.

    Args:
        db: Database session
        session_id: Session ID
        context_window_used: Current context window size
        tokens_used: Tokens used in this request
        cost: Cost of this request
    """
    result = await db.execute(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()

    if session:
        if context_window_used is not None:
            session.context_window_used = context_window_used

        if tokens_used is not None:
            session.total_tokens_used = (session.total_tokens_used or 0) + tokens_used

        if cost is not None:
            session.total_cost = Decimal(str(float(session.total_cost or 0) + cost))

        session.last_activity_at = datetime.utcnow()
        session.updated_at = datetime.utcnow()

        await db.commit()


async def update_session_status(
    db: AsyncSession,
    session_id: str,
    status: SessionStatus,
    user_id: Optional[str] = None
) -> Optional[ChatSession]:
    """
    Update session status.

    Args:
        db: Database session
        session_id: Session ID
        status: New status
        user_id: Optional user ID for ownership validation

    Returns:
        Updated session or None
    """
    session = await get_session(db, session_id, user_id)

    if session:
        session.status = status
        session.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(session)

    return session


async def delete_session(
    db: AsyncSession,
    session_id: str,
    user_id: Optional[str] = None
) -> bool:
    """
    Delete a session and all related data.

    Args:
        db: Database session
        session_id: Session ID
        user_id: Optional user ID for ownership validation

    Returns:
        True if deleted, False if not found
    """
    session = await get_session(db, session_id, user_id)

    if not session:
        return False

    await db.delete(session)
    await db.commit()

    return True


async def expire_stale_sessions(
    db: AsyncSession,
    batch_size: int = 100
) -> int:
    """
    Mark expired sessions as expired (background cleanup job).

    Args:
        db: Database session
        batch_size: Max sessions to process

    Returns:
        Number of sessions expired
    """
    now = datetime.utcnow()

    result = await db.execute(
        update(ChatSession)
        .where(
            ChatSession.status == SessionStatus.active,
            ChatSession.expires_at < now
        )
        .values(status=SessionStatus.expired, updated_at=now)
        .returning(ChatSession.id)
    )

    expired_ids = result.scalars().all()
    await db.commit()

    return len(expired_ids)


async def cleanup_expired_sessions(
    db: AsyncSession,
    older_than_days: int = 30,
    batch_size: int = 100
) -> int:
    """
    Delete expired sessions older than specified days.

    Args:
        db: Database session
        older_than_days: Delete sessions expired longer than this
        batch_size: Max sessions to delete

    Returns:
        Number of sessions deleted
    """
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)

    # Find sessions to delete
    result = await db.execute(
        select(ChatSession.id)
        .where(
            ChatSession.status == SessionStatus.expired,
            ChatSession.updated_at < cutoff
        )
        .limit(batch_size)
    )

    session_ids = result.scalars().all()

    if session_ids:
        await db.execute(
            delete(ChatSession).where(ChatSession.id.in_(session_ids))
        )
        await db.commit()

    return len(session_ids)
