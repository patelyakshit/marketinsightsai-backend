"""
Goal Service

Implements Todo.md style goal tracking.
Goals are placed at the END of context to combat "lost-in-the-middle" effect.
"""

import re
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionGoal, GoalStatus


async def add_goal(
    db: AsyncSession,
    session_id: str,
    goal_text: str,
    parent_goal_id: Optional[str] = None,
    priority: int = 0
) -> SessionGoal:
    """
    Add a new goal to a session.

    Args:
        db: Database session
        session_id: Session ID
        goal_text: Goal description
        parent_goal_id: Optional parent goal for subtasks
        priority: Goal priority (higher = more important)

    Returns:
        Created SessionGoal
    """
    goal = SessionGoal(
        id=str(uuid.uuid4()),
        session_id=session_id,
        goal_text=goal_text,
        status=GoalStatus.pending,
        priority=priority,
        parent_goal_id=parent_goal_id,
    )

    db.add(goal)
    await db.commit()
    await db.refresh(goal)

    return goal


async def get_goal(
    db: AsyncSession,
    goal_id: str
) -> Optional[SessionGoal]:
    """
    Get a goal by ID.

    Args:
        db: Database session
        goal_id: Goal ID

    Returns:
        SessionGoal or None
    """
    result = await db.execute(
        select(SessionGoal).where(SessionGoal.id == goal_id)
    )
    return result.scalar_one_or_none()


async def get_goals(
    db: AsyncSession,
    session_id: str,
    status: Optional[GoalStatus] = None
) -> list[SessionGoal]:
    """
    Get goals for a session.

    Args:
        db: Database session
        session_id: Session ID
        status: Optional status filter

    Returns:
        List of SessionGoal
    """
    query = (
        select(SessionGoal)
        .where(SessionGoal.session_id == session_id)
        .order_by(SessionGoal.priority.desc(), SessionGoal.created_at.asc())
    )

    if status:
        query = query.where(SessionGoal.status == status)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_active_goals(
    db: AsyncSession,
    session_id: str
) -> list[SessionGoal]:
    """
    Get all non-completed goals for context recitation.

    Args:
        db: Database session
        session_id: Session ID

    Returns:
        List of active SessionGoal (in_progress and pending)
    """
    result = await db.execute(
        select(SessionGoal)
        .where(
            SessionGoal.session_id == session_id,
            SessionGoal.status.in_([GoalStatus.pending, GoalStatus.in_progress])
        )
        .order_by(SessionGoal.priority.desc(), SessionGoal.created_at.asc())
    )
    return list(result.scalars().all())


async def update_goal(
    db: AsyncSession,
    goal_id: str,
    goal_text: Optional[str] = None,
    status: Optional[GoalStatus] = None,
    priority: Optional[int] = None
) -> Optional[SessionGoal]:
    """
    Update a goal's text, status, or priority.

    Args:
        db: Database session
        goal_id: Goal ID
        goal_text: New goal text (optional)
        status: New status (optional)
        priority: New priority (optional)

    Returns:
        Updated SessionGoal or None
    """
    goal = await get_goal(db, goal_id)

    if not goal:
        return None

    if goal_text is not None:
        goal.goal_text = goal_text

    if status is not None:
        goal.status = status
        if status == GoalStatus.completed:
            goal.completed_at = datetime.utcnow()
        elif status != GoalStatus.completed and goal.completed_at:
            goal.completed_at = None

    if priority is not None:
        goal.priority = priority

    goal.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(goal)

    return goal


async def update_goal_status(
    db: AsyncSession,
    goal_id: str,
    status: GoalStatus
) -> Optional[SessionGoal]:
    """
    Update just the status of a goal.

    Args:
        db: Database session
        goal_id: Goal ID
        status: New status

    Returns:
        Updated SessionGoal or None
    """
    return await update_goal(db, goal_id, status=status)


async def complete_goal(
    db: AsyncSession,
    goal_id: str
) -> Optional[SessionGoal]:
    """
    Mark a goal as completed.

    Args:
        db: Database session
        goal_id: Goal ID

    Returns:
        Updated SessionGoal or None
    """
    return await update_goal_status(db, goal_id, GoalStatus.completed)


async def cancel_goal(
    db: AsyncSession,
    goal_id: str
) -> Optional[SessionGoal]:
    """
    Mark a goal as cancelled.

    Args:
        db: Database session
        goal_id: Goal ID

    Returns:
        Updated SessionGoal or None
    """
    return await update_goal_status(db, goal_id, GoalStatus.cancelled)


async def start_goal(
    db: AsyncSession,
    goal_id: str
) -> Optional[SessionGoal]:
    """
    Mark a goal as in progress.

    Args:
        db: Database session
        goal_id: Goal ID

    Returns:
        Updated SessionGoal or None
    """
    return await update_goal_status(db, goal_id, GoalStatus.in_progress)


async def delete_goal(
    db: AsyncSession,
    goal_id: str
) -> bool:
    """
    Delete a goal.

    Args:
        db: Database session
        goal_id: Goal ID

    Returns:
        True if deleted, False if not found
    """
    goal = await get_goal(db, goal_id)

    if not goal:
        return False

    await db.delete(goal)
    await db.commit()

    return True


def format_goals_for_context(goals: list[SessionGoal]) -> str:
    """
    Format goals as markdown todo list for context.

    This is placed at the END of context to leverage recency bias
    and combat the "lost-in-the-middle" phenomenon.

    Args:
        goals: List of session goals

    Returns:
        Formatted markdown string
    """
    if not goals:
        return ""

    lines = ["## Current Objectives"]

    # Group by status for better organization
    in_progress = [g for g in goals if g.status == GoalStatus.in_progress]
    pending = [g for g in goals if g.status == GoalStatus.pending]
    completed = [g for g in goals if g.status == GoalStatus.completed]

    # In progress (most important, show first)
    for goal in in_progress:
        prefix = "- [ ] **"
        suffix = "** (in progress)"
        lines.append(f"{prefix}{goal.goal_text}{suffix}")

        # Show subtasks if any
        sub_goals = [g for g in goals if g.parent_goal_id == goal.id]
        for sub in sub_goals:
            status_mark = "x" if sub.status == GoalStatus.completed else " "
            lines.append(f"  - [{status_mark}] {sub.goal_text}")

    # Pending goals
    for goal in pending:
        if goal.parent_goal_id:
            continue  # Skip subtasks, shown under parents
        lines.append(f"- [ ] {goal.goal_text}")

        # Show subtasks if any
        sub_goals = [g for g in goals if g.parent_goal_id == goal.id]
        for sub in sub_goals:
            status_mark = "x" if sub.status == GoalStatus.completed else " "
            lines.append(f"  - [{status_mark}] {sub.goal_text}")

    # Recently completed (last 3, for context)
    recent_completed = completed[-3:]
    for goal in recent_completed:
        if goal.parent_goal_id:
            continue
        lines.append(f"- [x] ~~{goal.goal_text}~~ (done)")

    return "\n".join(lines)


def parse_goals_from_response(
    response: str
) -> list[dict]:
    """
    Extract goal-like statements from AI response.

    Looks for patterns like:
    - "I will..."
    - "Let me..."
    - "First, I'll..."
    - "Next steps:"
    - Numbered lists of tasks

    Args:
        response: AI response text

    Returns:
        List of potential goal dicts with 'text' key
    """
    goals = []

    # Pattern 1: "I will..." or "I'll..."
    will_patterns = re.findall(r"I(?:'ll| will) ([^.!?]+[.!?])", response, re.IGNORECASE)
    for match in will_patterns:
        goals.append({"text": match.strip().rstrip(".!?")})

    # Pattern 2: "Let me..." or "Let's..."
    let_patterns = re.findall(r"Let(?:'s| me) ([^.!?]+[.!?])", response, re.IGNORECASE)
    for match in let_patterns:
        goals.append({"text": match.strip().rstrip(".!?")})

    # Pattern 3: "First/Next/Then, I..."
    sequence_patterns = re.findall(
        r"(?:First|Next|Then|Finally),?\s+(?:I(?:'ll| will))?\s*([^.!?]+[.!?])",
        response,
        re.IGNORECASE
    )
    for match in sequence_patterns:
        goals.append({"text": match.strip().rstrip(".!?")})

    # Pattern 4: Numbered list items (1. Do something)
    numbered_patterns = re.findall(r"^\d+\.\s+(.+)$", response, re.MULTILINE)
    for match in numbered_patterns:
        if len(match) > 10:  # Filter out very short items
            goals.append({"text": match.strip()})

    # Pattern 5: Bullet points that look like tasks
    bullet_patterns = re.findall(r"^[-*]\s+(.+)$", response, re.MULTILINE)
    for match in bullet_patterns:
        # Filter to likely tasks (verbs or action words)
        if re.match(r"^(Create|Generate|Analyze|Build|Update|Review|Check|Find|Search)", match, re.IGNORECASE):
            goals.append({"text": match.strip()})

    # Deduplicate
    seen = set()
    unique_goals = []
    for goal in goals:
        if goal["text"].lower() not in seen:
            seen.add(goal["text"].lower())
            unique_goals.append(goal)

    return unique_goals


async def add_goals_from_response(
    db: AsyncSession,
    session_id: str,
    response: str
) -> list[SessionGoal]:
    """
    Parse AI response and add detected goals.

    Args:
        db: Database session
        session_id: Session ID
        response: AI response text

    Returns:
        List of created SessionGoal
    """
    parsed_goals = parse_goals_from_response(response)

    created_goals = []
    for i, goal_data in enumerate(parsed_goals):
        goal = await add_goal(
            db=db,
            session_id=session_id,
            goal_text=goal_data["text"],
            priority=len(parsed_goals) - i,  # Earlier goals have higher priority
        )
        created_goals.append(goal)

    return created_goals
