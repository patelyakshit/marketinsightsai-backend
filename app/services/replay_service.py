"""
Session Replay Service

Enables playback of agent sessions, showing step-by-step
how the AI completed a task.

Features:
- Timeline-based replay
- Speed control
- Event filtering
- Export to different formats
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, AsyncGenerator
from enum import Enum

from app.utils.datetime_utils import utc_now

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import ChatSession, SessionEvent, SessionGoal

logger = logging.getLogger(__name__)


class ReplaySpeed(str, Enum):
    """Replay speed options."""
    SLOW = "slow"  # 2x slower
    NORMAL = "normal"  # Real-time
    FAST = "fast"  # 2x faster
    INSTANT = "instant"  # No delays


@dataclass
class ReplayEvent:
    """A single event in the replay timeline."""
    sequence: int
    event_type: str
    content: str
    timestamp: datetime
    duration_ms: float
    metadata: dict = field(default_factory=dict)

    # Display properties
    display_type: str = ""  # "user", "agent", "tool", "result", "goal"
    display_title: str = ""
    display_icon: str = ""

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "display": {
                "type": self.display_type,
                "title": self.display_title,
                "icon": self.display_icon,
            }
        }


@dataclass
class ReplayTimeline:
    """Complete timeline for session replay."""
    session_id: str
    title: str
    total_events: int
    total_duration_ms: float
    events: list[ReplayEvent]
    goals: list[dict]
    summary: dict

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "total_events": self.total_events,
            "total_duration_ms": self.total_duration_ms,
            "events": [e.to_dict() for e in self.events],
            "goals": self.goals,
            "summary": self.summary,
        }


def get_display_properties(event_type: str, metadata: dict) -> tuple[str, str, str]:
    """Get display properties based on event type."""
    display_map = {
        "user": ("user", "User Input", "👤"),
        "assistant": ("agent", "AI Response", "🤖"),
        "action": ("tool", f"Tool: {metadata.get('tool', 'Unknown')}", "🔧"),
        "observation": ("result", "Tool Result", "📊"),
        "plan": ("agent", "Planning", "📋"),
        "goal_created": ("goal", "Goal Created", "🎯"),
        "goal_completed": ("goal", "Goal Completed", "✅"),
        "error": ("error", "Error", "❌"),
    }
    return display_map.get(event_type, ("unknown", event_type, "📌"))


async def build_replay_timeline(
    db: AsyncSession,
    session_id: str,
    user_id: str,
) -> Optional[ReplayTimeline]:
    """
    Build a complete replay timeline for a session.

    Args:
        db: Database session
        session_id: Session to replay
        user_id: User ID for authorization

    Returns:
        ReplayTimeline or None if not found
    """
    # Verify session
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        return None

    # Get all events
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

    # Build replay events
    replay_events = []
    prev_time = session.created_at
    total_duration = 0

    for event in events:
        # Calculate duration since last event
        if event.created_at and prev_time:
            duration = (event.created_at - prev_time).total_seconds() * 1000
        else:
            duration = 100  # Default 100ms

        total_duration += duration
        prev_time = event.created_at

        # Get display properties
        metadata = event.metadata or {}
        display_type, display_title, display_icon = get_display_properties(
            event.event_type, metadata
        )

        replay_events.append(ReplayEvent(
            sequence=event.sequence_number,
            event_type=event.event_type,
            content=event.content or "",
            timestamp=event.created_at or utc_now(),
            duration_ms=duration,
            metadata=metadata,
            display_type=display_type,
            display_title=display_title,
            display_icon=display_icon,
        ))

    # Build summary
    summary = {
        "total_tokens": sum(e.token_count or 0 for e in events),
        "tool_calls": sum(1 for e in events if e.event_type == "action"),
        "user_messages": sum(1 for e in events if e.event_type == "user"),
        "ai_responses": sum(1 for e in events if e.event_type == "assistant"),
        "goals_completed": sum(1 for g in goals if g.status == "completed"),
        "goals_total": len(goals),
    }

    return ReplayTimeline(
        session_id=session_id,
        title=session.title or "Untitled Session",
        total_events=len(replay_events),
        total_duration_ms=total_duration,
        events=replay_events,
        goals=[
            {
                "id": str(g.id),
                "text": g.goal_text,
                "status": g.status,
                "order": g.order_index,
            }
            for g in goals
        ],
        summary=summary,
    )


async def stream_replay_events(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    speed: ReplaySpeed = ReplaySpeed.NORMAL,
) -> AsyncGenerator[dict, None]:
    """
    Stream replay events with timing.

    Yields events with appropriate delays based on speed setting.
    Use with SSE or WebSocket for real-time streaming.

    Args:
        db: Database session
        session_id: Session to replay
        user_id: User ID
        speed: Replay speed

    Yields:
        Event dicts
    """
    import asyncio

    timeline = await build_replay_timeline(db, session_id, user_id)

    if not timeline:
        yield {"error": "Session not found"}
        return

    # Speed multipliers
    speed_mult = {
        ReplaySpeed.SLOW: 2.0,
        ReplaySpeed.NORMAL: 1.0,
        ReplaySpeed.FAST: 0.5,
        ReplaySpeed.INSTANT: 0.0,
    }
    mult = speed_mult.get(speed, 1.0)

    # Yield session info first
    yield {
        "type": "session_start",
        "session_id": session_id,
        "title": timeline.title,
        "total_events": timeline.total_events,
        "total_duration_ms": timeline.total_duration_ms,
    }

    # Stream events
    for i, event in enumerate(timeline.events):
        # Delay based on speed
        if mult > 0 and event.duration_ms > 0:
            delay = min(event.duration_ms * mult / 1000, 2.0)  # Max 2 second delay
            await asyncio.sleep(delay)

        yield {
            "type": "event",
            "progress": (i + 1) / timeline.total_events,
            "event": event.to_dict(),
        }

    # Yield completion
    yield {
        "type": "session_end",
        "summary": timeline.summary,
    }


async def export_session_transcript(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    format: str = "markdown",
) -> Optional[str]:
    """
    Export session as a readable transcript.

    Args:
        db: Database session
        session_id: Session to export
        user_id: User ID
        format: "markdown", "text", or "json"

    Returns:
        Formatted transcript string
    """
    timeline = await build_replay_timeline(db, session_id, user_id)

    if not timeline:
        return None

    if format == "json":
        return json.dumps(timeline.to_dict(), indent=2)

    # Build markdown/text
    lines = []

    if format == "markdown":
        lines.append(f"# {timeline.title}")
        lines.append("")
        lines.append(f"**Session ID:** {timeline.session_id}")
        lines.append(f"**Total Events:** {timeline.total_events}")
        lines.append(f"**Duration:** {timeline.total_duration_ms / 1000:.1f}s")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Goals
        if timeline.goals:
            lines.append("## Goals")
            for goal in timeline.goals:
                status_icon = "✅" if goal["status"] == "completed" else "⏳"
                lines.append(f"- {status_icon} {goal['text']}")
            lines.append("")

        # Events
        lines.append("## Timeline")
        lines.append("")

        for event in timeline.events:
            icon = event.display_icon
            title = event.display_title

            if event.event_type == "user":
                lines.append(f"### {icon} User")
                lines.append(f"> {event.content}")
            elif event.event_type == "assistant":
                lines.append(f"### {icon} AI Response")
                lines.append(event.content[:500])
            elif event.event_type == "action":
                tool = event.metadata.get("tool", "Unknown")
                lines.append(f"### {icon} Tool Call: {tool}")
                if event.metadata.get("params"):
                    lines.append(f"```json\n{json.dumps(event.metadata['params'], indent=2)}\n```")
            elif event.event_type == "observation":
                lines.append(f"### {icon} Result")
                lines.append(f"```\n{event.content[:300]}\n```")

            lines.append("")

        # Summary
        lines.append("---")
        lines.append("")
        lines.append("## Summary")
        lines.append(f"- Tokens used: {timeline.summary['total_tokens']}")
        lines.append(f"- Tool calls: {timeline.summary['tool_calls']}")
        lines.append(f"- Goals completed: {timeline.summary['goals_completed']}/{timeline.summary['goals_total']}")

    else:  # Plain text
        lines.append(f"SESSION: {timeline.title}")
        lines.append(f"ID: {timeline.session_id}")
        lines.append("=" * 50)
        lines.append("")

        for event in timeline.events:
            lines.append(f"[{event.display_type.upper()}] {event.display_title}")
            lines.append(event.content[:200])
            lines.append("")

    return "\n".join(lines)


async def get_session_highlights(
    db: AsyncSession,
    session_id: str,
    user_id: str,
) -> Optional[dict]:
    """
    Get key highlights from a session for quick overview.

    Returns:
        Dict with highlights or None
    """
    timeline = await build_replay_timeline(db, session_id, user_id)

    if not timeline:
        return None

    # Find key moments
    highlights = {
        "session_id": session_id,
        "title": timeline.title,
        "first_user_message": None,
        "final_response": None,
        "tools_used": [],
        "goals_achieved": [],
        "errors": [],
    }

    for event in timeline.events:
        if event.event_type == "user" and not highlights["first_user_message"]:
            highlights["first_user_message"] = event.content[:200]

        if event.event_type == "assistant":
            highlights["final_response"] = event.content[:300]

        if event.event_type == "action":
            tool = event.metadata.get("tool")
            if tool and tool not in highlights["tools_used"]:
                highlights["tools_used"].append(tool)

        if event.event_type == "error":
            highlights["errors"].append(event.content[:100])

    for goal in timeline.goals:
        if goal["status"] == "completed":
            highlights["goals_achieved"].append(goal["text"])

    highlights["summary"] = timeline.summary

    return highlights
