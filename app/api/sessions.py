"""
Sessions API Router

Provides endpoints for managing chat sessions with context engineering.
All endpoints require authentication.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User, SessionStatus as DBSessionStatus
from app.api.deps import get_current_user
from app.models.schemas import (
    SessionCreate, SessionResponse, SessionListResponse,
    SessionStatus, SessionUsageStats, EventListResponse, EventResponse,
    GoalListResponse, GoalResponse, GoalCreate, GoalUpdate, GoalStatus,
)
from app.services.context import session_service, token_service


router = APIRouter()


def _session_to_response(session) -> SessionResponse:
    """Convert database session to response schema."""
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        folder_id=session.folder_id,
        title=session.title,
        status=SessionStatus(session.status.value),
        context_window_used=session.context_window_used or 0,
        total_tokens_used=session.total_tokens_used or 0,
        total_cost=float(session.total_cost or 0),
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_activity_at=session.last_activity_at,
        expires_at=session.expires_at,
    )


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    data: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new chat session.

    Sessions are required for context-aware conversations with history persistence.
    """
    session = await session_service.create_session(
        db=db,
        user_id=current_user.id,
        folder_id=data.folder_id,
        title=data.title,
    )

    return _session_to_response(session)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    status: SessionStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List chat sessions for the current user.

    Supports filtering by status and pagination.
    """
    db_status = None
    if status:
        db_status = DBSessionStatus(status.value)

    sessions, total = await session_service.list_user_sessions(
        db=db,
        user_id=current_user.id,
        status=db_status,
        limit=limit,
        offset=offset,
    )

    return SessionListResponse(
        sessions=[_session_to_response(s) for s in sessions],
        total=total,
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific chat session.
    """
    session = await session_service.get_session(db, session_id, current_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    return _session_to_response(session)


@router.patch("/{session_id}/status", response_model=SessionResponse)
async def update_session_status(
    session_id: str,
    new_status: SessionStatus,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update session status (pause, complete, etc.).
    """
    session = await session_service.update_session_status(
        db=db,
        session_id=session_id,
        status=DBSessionStatus(new_status.value),
        user_id=current_user.id,
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    return _session_to_response(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a chat session and all related data.
    """
    deleted = await session_service.delete_session(db, session_id, current_user.id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )


@router.get("/{session_id}/usage", response_model=SessionUsageStats)
async def get_session_usage(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get token usage and cost statistics for a session.
    """
    # Verify ownership
    session = await session_service.get_session(db, session_id, current_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    usage = await token_service.get_session_usage(db, session_id)

    return SessionUsageStats(
        session_id=usage["session_id"],
        total_requests=usage["total_requests"],
        total_input_tokens=usage["total_input_tokens"],
        total_output_tokens=usage["total_output_tokens"],
        total_cached_tokens=usage["total_cached_tokens"],
        total_cost_usd=usage["total_cost_usd"],
        cache_hit_rate=usage["cache_hit_rate"],
    )


@router.get("/{session_id}/events", response_model=EventListResponse)
async def get_session_events(
    session_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get event history for a session.
    """
    # Import here to avoid circular import
    from app.services.context import event_stream_service

    # Verify ownership
    session = await session_service.get_session(db, session_id, current_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    events, total = await event_stream_service.get_events(
        db=db,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )

    return EventListResponse(
        events=[
            EventResponse(
                id=e.id,
                session_id=e.session_id,
                sequence_num=e.sequence_num,
                event_type=e.event_type.value,
                content=e.content if isinstance(e.content, dict) else {"text": e.content},
                token_count=e.token_count or 0,
                cached_tokens=e.cached_tokens or 0,
                metadata=e.event_metadata or {},
                created_at=e.created_at,
            )
            for e in events
        ],
        total=total,
    )


@router.get("/{session_id}/goals", response_model=GoalListResponse)
async def get_session_goals(
    session_id: str,
    status: GoalStatus | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get goals for a session.
    """
    # Import here to avoid circular import
    from app.services.context import goal_service

    # Verify ownership
    session = await session_service.get_session(db, session_id, current_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    from app.db.models import GoalStatus as DBGoalStatus
    db_status = DBGoalStatus(status.value) if status else None

    goals = await goal_service.get_goals(db, session_id, db_status)

    return GoalListResponse(
        goals=[
            GoalResponse(
                id=g.id,
                session_id=g.session_id,
                goal_text=g.goal_text,
                status=GoalStatus(g.status.value),
                priority=g.priority,
                parent_goal_id=g.parent_goal_id,
                created_at=g.created_at,
                updated_at=g.updated_at,
                completed_at=g.completed_at,
            )
            for g in goals
        ]
    )


@router.post("/{session_id}/goals", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    session_id: str,
    data: GoalCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Add a goal to a session.
    """
    from app.services.context import goal_service

    # Verify ownership
    session = await session_service.get_session(db, session_id, current_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    goal = await goal_service.add_goal(
        db=db,
        session_id=session_id,
        goal_text=data.goal_text,
        parent_goal_id=data.parent_goal_id,
        priority=data.priority,
    )

    return GoalResponse(
        id=goal.id,
        session_id=goal.session_id,
        goal_text=goal.goal_text,
        status=GoalStatus(goal.status.value),
        priority=goal.priority,
        parent_goal_id=goal.parent_goal_id,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        completed_at=goal.completed_at,
    )


@router.patch("/{session_id}/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(
    session_id: str,
    goal_id: str,
    data: GoalUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a goal's status or text.
    """
    from app.services.context import goal_service

    # Verify session ownership
    session = await session_service.get_session(db, session_id, current_user.id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    from app.db.models import GoalStatus as DBGoalStatus
    db_status = DBGoalStatus(data.status.value) if data.status else None

    goal = await goal_service.update_goal(
        db=db,
        goal_id=goal_id,
        goal_text=data.goal_text,
        status=db_status,
        priority=data.priority,
    )

    if not goal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Goal not found"
        )

    return GoalResponse(
        id=goal.id,
        session_id=goal.session_id,
        goal_text=goal.goal_text,
        status=GoalStatus(goal.status.value),
        priority=goal.priority,
        parent_goal_id=goal.parent_goal_id,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        completed_at=goal.completed_at,
    )
