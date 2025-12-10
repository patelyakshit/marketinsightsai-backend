"""
Agent API Router

Endpoints for the Transparency UI / Agent Workspace.
Shows real-time agent execution progress, decision-making, and task history.

Inspired by Manus AI's "Computer" view that shows:
- Current agent state and actions
- Tool calls and their results
- Thought process and reasoning
- Progress through task steps
"""

from typing import Optional
from uuid import uuid4

from app.utils.datetime_utils import utc_now

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.db.database import get_db
from app.db.models import User, ChatSession, SessionEvent, SessionGoal
from app.api.deps import get_current_user

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class AgentStepResponse(BaseModel):
    """A single step in agent execution."""
    id: str
    step_number: int
    agent_type: str  # orchestrator, planner, executor, verifier
    action: str
    status: str  # pending, running, completed, failed
    thought: Optional[str] = None  # Agent's reasoning
    tool_name: Optional[str] = None
    tool_params: Optional[dict] = None
    tool_result: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None


class AgentProgressResponse(BaseModel):
    """Current agent execution progress."""
    session_id: str
    status: str  # idle, planning, executing, verifying, completed, error
    current_step: int
    total_steps: int
    progress_percent: float
    current_agent: Optional[str] = None
    current_action: Optional[str] = None
    steps: list[AgentStepResponse]
    goals: list[dict]
    tokens_used: int
    started_at: Optional[str] = None
    elapsed_ms: Optional[float] = None


class AgentSessionSummary(BaseModel):
    """Summary of an agent session."""
    session_id: str
    title: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    total_steps: int
    tokens_used: int
    tools_called: int
    success: bool


class AgentHistoryResponse(BaseModel):
    """List of agent sessions."""
    sessions: list[AgentSessionSummary]
    total: int
    page: int
    page_size: int


class StartAgentTaskRequest(BaseModel):
    """Request to start an agent task."""
    task: str = Field(..., description="Task description")
    task_type: Optional[str] = Field(None, description="Optional task type hint")
    context: Optional[dict] = Field(None, description="Additional context")


class StartAgentTaskResponse(BaseModel):
    """Response when agent task is started."""
    session_id: str
    status: str
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/start", response_model=StartAgentTaskResponse)
async def start_agent_task(
    request: StartAgentTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a new agent task.

    Creates a new session and begins agent execution.
    Use /agent/progress/{session_id} to monitor progress.
    """
    from app.services.agent_service import AgentService
    from app.services.context import create_session

    try:
        # Create a new session
        session = await create_session(
            db=db,
            user_id=str(current_user.id),
            title=request.task[:100],
            metadata={"task_type": request.task_type} if request.task_type else {},
        )

        # Start agent execution in background
        from app.utils.async_utils import create_task_with_error_handling
        agent_service = AgentService(db=db, session_id=session.id)

        # Queue the task (non-blocking) with proper error handling
        create_task_with_error_handling(
            agent_service.process_request(
                user_message=request.task,
                context=request.context,
            ),
            task_name=f"agent_task_{session.id}"
        )

        return StartAgentTaskResponse(
            session_id=session.id,
            status="started",
            message="Agent task started. Monitor progress at /api/agent/progress/{session_id}",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start agent task: {str(e)}"
        )


@router.get("/progress/{session_id}", response_model=AgentProgressResponse)
async def get_agent_progress(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get real-time progress of an agent task.

    Returns current state, steps completed, and agent reasoning.
    Poll this endpoint for live updates (or use WebSocket for streaming).
    """
    # Verify session exists and belongs to user
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == str(current_user.id),
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Get events for this session
    events_result = await db.execute(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.sequence_number)
    )
    events = events_result.scalars().all()

    # Get goals
    goals_result = await db.execute(
        select(SessionGoal)
        .where(SessionGoal.session_id == session_id)
        .order_by(SessionGoal.order_index)
    )
    goals = goals_result.scalars().all()

    # Build steps from events
    steps = []
    step_number = 0
    tokens_used = 0

    for event in events:
        tokens_used += event.token_count or 0

        if event.event_type in ("action", "plan", "assistant"):
            step_number += 1

            # Parse metadata for agent info
            metadata = event.metadata or {}

            steps.append(AgentStepResponse(
                id=str(event.id),
                step_number=step_number,
                agent_type=metadata.get("agent", "executor"),
                action=event.content[:200] if event.content else "",
                status="completed",
                thought=metadata.get("thought"),
                tool_name=metadata.get("tool"),
                tool_params=metadata.get("params"),
                tool_result=None,  # Will be in observation event
                started_at=event.created_at.isoformat() if event.created_at else None,
                completed_at=event.created_at.isoformat() if event.created_at else None,
            ))

    # Determine current status
    status_str = "idle"
    if session.metadata:
        status_str = session.metadata.get("status", "idle")
    if steps and not session.metadata.get("completed"):
        status_str = "executing"

    # Calculate progress
    total_goals = len(goals)
    completed_goals = sum(1 for g in goals if g.status == "completed")
    progress = (completed_goals / total_goals * 100) if total_goals > 0 else 0

    return AgentProgressResponse(
        session_id=session_id,
        status=status_str,
        current_step=len(steps),
        total_steps=total_goals or len(steps),
        progress_percent=progress,
        current_agent=steps[-1].agent_type if steps else None,
        current_action=steps[-1].action if steps else None,
        steps=steps[-20:],  # Last 20 steps
        goals=[
            {
                "id": str(g.id),
                "text": g.goal_text,
                "status": g.status,
                "order": g.order_index,
            }
            for g in goals
        ],
        tokens_used=tokens_used,
        started_at=session.created_at.isoformat() if session.created_at else None,
        elapsed_ms=(utc_now() - session.created_at).total_seconds() * 1000 if session.created_at else None,
    )


@router.get("/history", response_model=AgentHistoryResponse)
async def get_agent_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get history of agent sessions for the current user.
    """
    offset = (page - 1) * page_size

    # Get sessions
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == str(current_user.id))
        .order_by(desc(ChatSession.created_at))
        .offset(offset)
        .limit(page_size)
    )
    sessions = result.scalars().all()

    # Count total
    count_result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == str(current_user.id))
    )
    total = len(count_result.scalars().all())

    summaries = []
    for session in sessions:
        # Get event stats
        events_result = await db.execute(
            select(SessionEvent)
            .where(SessionEvent.session_id == session.id)
        )
        events = events_result.scalars().all()

        tokens = sum(e.token_count or 0 for e in events)
        tools = sum(1 for e in events if e.event_type == "action")

        metadata = session.metadata or {}

        summaries.append(AgentSessionSummary(
            session_id=session.id,
            title=session.title or "Untitled Session",
            status=metadata.get("status", "unknown"),
            created_at=session.created_at.isoformat() if session.created_at else "",
            completed_at=metadata.get("completed_at"),
            total_steps=len(events),
            tokens_used=tokens,
            tools_called=tools,
            success=metadata.get("success", False),
        ))

    return AgentHistoryResponse(
        sessions=summaries,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/session/{session_id}/events")
async def get_session_events(
    session_id: str,
    event_types: Optional[str] = Query(None, description="Comma-separated event types to filter"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed events for a session.

    Returns the full event stream for session replay.
    """
    # Verify session belongs to user
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == str(current_user.id),
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Build query
    query = select(SessionEvent).where(SessionEvent.session_id == session_id)

    if event_types:
        types = [t.strip() for t in event_types.split(",")]
        query = query.where(SessionEvent.event_type.in_(types))

    query = query.order_by(SessionEvent.sequence_number).limit(limit)

    events_result = await db.execute(query)
    events = events_result.scalars().all()

    return {
        "session_id": session_id,
        "event_count": len(events),
        "events": [
            {
                "id": str(e.id),
                "sequence": e.sequence_number,
                "type": e.event_type,
                "content": e.content,
                "metadata": e.metadata,
                "tokens": e.token_count,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an agent session and all its data.
    """
    # Verify session belongs to user
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == str(current_user.id),
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Delete session (cascades to events, goals, etc.)
    await db.delete(session)
    await db.commit()

    return {"deleted": True, "session_id": session_id}


@router.get("/stats")
async def get_agent_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregate stats for user's agent usage.
    """
    # Get all sessions
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == str(current_user.id))
    )
    sessions = result.scalars().all()

    total_sessions = len(sessions)
    total_tokens = 0
    total_tools = 0
    successful = 0

    for session in sessions:
        events_result = await db.execute(
            select(SessionEvent)
            .where(SessionEvent.session_id == session.id)
        )
        events = events_result.scalars().all()

        total_tokens += sum(e.token_count or 0 for e in events)
        total_tools += sum(1 for e in events if e.event_type == "action")

        if session.metadata and session.metadata.get("success"):
            successful += 1

    return {
        "total_sessions": total_sessions,
        "successful_sessions": successful,
        "success_rate": (successful / total_sessions * 100) if total_sessions > 0 else 0,
        "total_tokens_used": total_tokens,
        "total_tool_calls": total_tools,
        "avg_tokens_per_session": total_tokens // total_sessions if total_sessions > 0 else 0,
    }
