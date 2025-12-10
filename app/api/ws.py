"""
WebSocket API for Real-Time Agent Progress

Provides real-time streaming of agent execution progress to clients.
Implements the transparency UI pattern from Manus AI.

Features:
- Real-time event streaming
- Progress updates for long-running tasks
- Goal completion notifications
- Error notifications
"""

import asyncio
import json
import logging
from typing import Optional
from uuid import uuid4

from app.utils.datetime_utils import utc_now

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.api.deps import get_current_user_ws
from app.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Connection Manager
# =============================================================================

class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        # Map session_id -> list of websocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}
        # Map connection_id -> (session_id, websocket)
        self.connection_map: dict[str, tuple[str, WebSocket]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str,
    ) -> str:
        """
        Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
            session_id: Session to subscribe to

        Returns:
            Connection ID
        """
        await websocket.accept()

        connection_id = str(uuid4())

        if session_id not in self.active_connections:
            self.active_connections[session_id] = []

        self.active_connections[session_id].append(websocket)
        self.connection_map[connection_id] = (session_id, websocket)

        logger.info(f"WebSocket connected: {connection_id} for session {session_id}")

        return connection_id

    def disconnect(self, connection_id: str) -> None:
        """
        Remove a WebSocket connection.

        Args:
            connection_id: The connection to remove
        """
        if connection_id not in self.connection_map:
            return

        session_id, websocket = self.connection_map[connection_id]

        if session_id in self.active_connections:
            try:
                self.active_connections[session_id].remove(websocket)
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]
            except ValueError:
                pass

        del self.connection_map[connection_id]
        logger.info(f"WebSocket disconnected: {connection_id}")

    async def send_to_session(
        self,
        session_id: str,
        message: dict,
    ) -> None:
        """
        Send a message to all connections for a session.

        Args:
            session_id: Target session
            message: Message dict to send
        """
        if session_id not in self.active_connections:
            return

        message_json = json.dumps(message)
        disconnected = []

        for websocket in self.active_connections[session_id]:
            try:
                await websocket.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to websocket: {e}")
                disconnected.append(websocket)

        # Clean up disconnected
        for ws in disconnected:
            try:
                self.active_connections[session_id].remove(ws)
            except ValueError:
                pass

    async def broadcast_progress(
        self,
        session_id: str,
        event_type: str,
        data: dict,
    ) -> None:
        """
        Broadcast a progress event to session subscribers.

        Args:
            session_id: Target session
            event_type: Type of progress event
            data: Event data
        """
        await self.send_to_session(session_id, {
            "type": event_type,
            "timestamp": utc_now().isoformat(),
            "data": data,
        })


# Global connection manager instance
manager = ConnectionManager()


# =============================================================================
# Progress Event Types
# =============================================================================

class ProgressEventType:
    """Event types for progress streaming."""
    # Agent lifecycle
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ERROR = "agent_error"

    # Execution progress
    PLAN_CREATED = "plan_created"
    STEP_START = "step_start"
    STEP_COMPLETE = "step_complete"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Goal tracking
    GOAL_CREATED = "goal_created"
    GOAL_UPDATED = "goal_updated"
    GOAL_COMPLETED = "goal_completed"

    # Content streaming
    TOKEN_STREAM = "token_stream"
    CONTENT_CHUNK = "content_chunk"

    # Session
    SESSION_UPDATE = "session_update"


# =============================================================================
# Helper Functions for Broadcasting
# =============================================================================

async def broadcast_agent_start(
    session_id: str,
    agent_name: str,
    task: str,
) -> None:
    """Broadcast that an agent has started execution."""
    await manager.broadcast_progress(session_id, ProgressEventType.AGENT_START, {
        "agent": agent_name,
        "task": task[:200],
    })


async def broadcast_agent_complete(
    session_id: str,
    agent_name: str,
    success: bool,
    output_preview: str,
    metrics: dict,
) -> None:
    """Broadcast that an agent has completed execution."""
    await manager.broadcast_progress(session_id, ProgressEventType.AGENT_COMPLETE, {
        "agent": agent_name,
        "success": success,
        "output_preview": output_preview[:500],
        "metrics": metrics,
    })


async def broadcast_plan_created(
    session_id: str,
    plan_summary: str,
    steps: list[dict],
) -> None:
    """Broadcast that a plan has been created."""
    await manager.broadcast_progress(session_id, ProgressEventType.PLAN_CREATED, {
        "summary": plan_summary,
        "steps": steps,
        "step_count": len(steps),
    })


async def broadcast_step_progress(
    session_id: str,
    step_id: str,
    step_description: str,
    status: str,  # "started", "completed", "failed"
    result: Optional[str] = None,
) -> None:
    """Broadcast step progress."""
    event_type = ProgressEventType.STEP_START if status == "started" else ProgressEventType.STEP_COMPLETE
    await manager.broadcast_progress(session_id, event_type, {
        "step_id": step_id,
        "description": step_description,
        "status": status,
        "result": result[:300] if result else None,
    })


async def broadcast_tool_call(
    session_id: str,
    tool_name: str,
    parameters: dict,
) -> None:
    """Broadcast that a tool is being called."""
    await manager.broadcast_progress(session_id, ProgressEventType.TOOL_CALL, {
        "tool": tool_name,
        "parameters": parameters,
    })


async def broadcast_tool_result(
    session_id: str,
    tool_name: str,
    success: bool,
    result_preview: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Broadcast tool execution result."""
    await manager.broadcast_progress(session_id, ProgressEventType.TOOL_RESULT, {
        "tool": tool_name,
        "success": success,
        "result_preview": result_preview[:200] if result_preview else None,
        "error": error,
    })


async def broadcast_goal_update(
    session_id: str,
    goal_id: str,
    goal_text: str,
    status: str,
) -> None:
    """Broadcast goal status update."""
    event_type = ProgressEventType.GOAL_COMPLETED if status == "completed" else ProgressEventType.GOAL_UPDATED
    await manager.broadcast_progress(session_id, event_type, {
        "goal_id": goal_id,
        "goal_text": goal_text,
        "status": status,
    })


async def broadcast_content_chunk(
    session_id: str,
    chunk: str,
    is_final: bool = False,
) -> None:
    """Broadcast a content chunk for streaming responses."""
    await manager.broadcast_progress(session_id, ProgressEventType.CONTENT_CHUNK, {
        "chunk": chunk,
        "is_final": is_final,
    })


# =============================================================================
# WebSocket Endpoint
# =============================================================================

@router.websocket("/stream/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(None),
):
    """
    WebSocket endpoint for real-time progress streaming.

    Connect to receive updates for a specific session.

    Query Parameters:
        token: JWT token for authentication (optional for now)

    Messages sent:
        - agent_start: Agent has started
        - agent_complete: Agent finished
        - plan_created: Execution plan created
        - step_start/step_complete: Step progress
        - tool_call/tool_result: Tool execution
        - goal_updated/goal_completed: Goal tracking
        - content_chunk: Streaming content

    Client can send:
        - {"type": "ping"}: Keepalive
        - {"type": "cancel"}: Cancel current execution (future)
    """
    connection_id = await manager.connect(websocket, session_id)

    try:
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "connection_id": connection_id,
            "session_id": session_id,
            "timestamp": utc_now().isoformat(),
        })

        # Listen for client messages
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0  # 60 second timeout for keepalive
                )

                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": utc_now().isoformat(),
                    })
                elif msg_type == "cancel":
                    # Future: implement cancellation
                    await websocket.send_json({
                        "type": "ack",
                        "message": "Cancellation not yet implemented",
                    })
                else:
                    logger.debug(f"Unknown message type: {msg_type}")

            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({
                        "type": "keepalive",
                        "timestamp": utc_now().isoformat(),
                    })
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.disconnect(connection_id)


# =============================================================================
# REST Endpoints for Checking Status
# =============================================================================

@router.get("/connections/{session_id}")
async def get_session_connections(session_id: str):
    """Get number of active connections for a session."""
    count = len(manager.active_connections.get(session_id, []))
    return {"session_id": session_id, "connection_count": count}


@router.get("/health")
async def websocket_health():
    """Health check for WebSocket service."""
    total_connections = sum(len(conns) for conns in manager.active_connections.values())
    return {
        "status": "healthy",
        "total_connections": total_connections,
        "active_sessions": len(manager.active_connections),
    }
