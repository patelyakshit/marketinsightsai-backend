"""
Background Task Queue Service

Async task queue for long-running operations using arq (Redis-backed).
Falls back to in-memory queue for development without Redis.

Features:
- Async task execution
- Task status tracking
- Progress updates
- Result storage
- Retry handling
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional

from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


# =============================================================================
# Task Status and Types
# =============================================================================

class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """Types of background tasks."""
    RESEARCH = "research"
    REPORT_GENERATION = "report_generation"
    SLIDE_GENERATION = "slide_generation"
    BATCH_ANALYSIS = "batch_analysis"
    DATA_EXPORT = "data_export"


@dataclass
class TaskProgress:
    """Progress update for a task."""
    task_id: str
    progress: float  # 0.0 to 1.0
    message: str
    step: int = 0
    total_steps: int = 1
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class TaskInfo:
    """Information about a queued task."""
    id: str
    task_type: TaskType
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    progress_message: str = ""
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "task_type": self.task_type.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


# =============================================================================
# In-Memory Task Queue (Development / Fallback)
# =============================================================================

class InMemoryTaskQueue:
    """
    Simple in-memory task queue for development and testing.

    In production, use Redis-backed arq for persistence and scalability.
    """

    def __init__(self):
        self.tasks: dict[str, TaskInfo] = {}
        self.handlers: dict[TaskType, Callable] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def register_handler(
        self,
        task_type: TaskType,
        handler: Callable,
    ) -> None:
        """Register a handler for a task type."""
        self.handlers[task_type] = handler
        logger.info(f"Registered handler for task type: {task_type.value}")

    async def enqueue(
        self,
        task_type: TaskType,
        params: dict,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Add a task to the queue.

        Args:
            task_type: Type of task
            params: Parameters for the task handler
            metadata: Optional metadata (user_id, etc.)

        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())

        task_info = TaskInfo(
            id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=utc_now(),
            metadata=metadata or {},
        )
        task_info.metadata["params"] = params

        async with self._lock:
            self.tasks[task_id] = task_info

        # Start the task asynchronously with proper error handling
        from app.utils.async_utils import create_task_with_error_handling
        create_task_with_error_handling(
            self._execute_task(task_id, task_type, params),
            task_name=f"task_{task_type.value}_{task_id}"
        )

        logger.info(f"Enqueued task {task_id} of type {task_type.value}")
        return task_id

    async def _execute_task(
        self,
        task_id: str,
        task_type: TaskType,
        params: dict,
    ) -> None:
        """Execute a task."""
        handler = self.handlers.get(task_type)

        if not handler:
            await self._update_task(
                task_id,
                status=TaskStatus.FAILED,
                error=f"No handler for task type: {task_type.value}",
            )
            return

        # Update status to running
        await self._update_task(
            task_id,
            status=TaskStatus.RUNNING,
            started_at=utc_now(),
        )

        try:
            # Create progress callback
            async def update_progress(progress: float, message: str = ""):
                await self._update_task(
                    task_id,
                    progress=progress,
                    progress_message=message,
                )

            # Execute handler
            result = await handler(params, update_progress)

            # Update with result
            await self._update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                completed_at=utc_now(),
                progress=1.0,
                result=result,
            )

            logger.info(f"Task {task_id} completed successfully")

        except asyncio.CancelledError:
            await self._update_task(
                task_id,
                status=TaskStatus.CANCELLED,
                completed_at=utc_now(),
            )
            logger.info(f"Task {task_id} was cancelled")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            await self._update_task(
                task_id,
                status=TaskStatus.FAILED,
                completed_at=utc_now(),
                error=str(e),
            )

    async def _update_task(
        self,
        task_id: str,
        **updates,
    ) -> None:
        """Update task info."""
        async with self._lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                for key, value in updates.items():
                    if hasattr(task, key):
                        setattr(task, key, value)

    async def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task info by ID."""
        return self.tasks.get(task_id)

    async def get_tasks_by_user(
        self,
        user_id: str,
        limit: int = 20,
    ) -> list[TaskInfo]:
        """Get tasks for a user."""
        user_tasks = [
            t for t in self.tasks.values()
            if t.metadata.get("user_id") == user_id
        ]
        # Sort by created_at descending
        user_tasks.sort(key=lambda t: t.created_at, reverse=True)
        return user_tasks[:limit]

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        if task_id in self._running_tasks:
            self._running_tasks[task_id].cancel()
            return True
        return False

    async def cleanup_old_tasks(
        self,
        max_age_hours: int = 24,
    ) -> int:
        """Remove old completed/failed tasks."""
        cutoff = utc_now() - timedelta(hours=max_age_hours)
        removed = 0

        async with self._lock:
            old_ids = [
                tid for tid, task in self.tasks.items()
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                and task.created_at < cutoff
            ]
            for tid in old_ids:
                del self.tasks[tid]
                removed += 1

        return removed


# =============================================================================
# Global Task Queue Instance
# =============================================================================

# Use in-memory queue (can be replaced with Redis-backed arq in production)
task_queue = InMemoryTaskQueue()


# =============================================================================
# Task Handlers
# =============================================================================

async def research_task_handler(
    params: dict,
    update_progress: Callable,
) -> dict:
    """
    Handler for research tasks.

    Args:
        params: {"query": str, "context": dict, "user_id": str}
        update_progress: Callback for progress updates

    Returns:
        Research result dict
    """
    from app.agents.specialists import ResearchAgent

    await update_progress(0.1, "Starting research...")

    query = params.get("query", "")
    context = params.get("context")

    # Create research agent
    agent = ResearchAgent()

    await update_progress(0.2, "Searching the web...")

    # Execute research
    result = await agent.execute(query, context)

    await update_progress(0.9, "Compiling results...")

    return {
        "success": result.success,
        "output": result.output,
        "sources": result.metadata.get("sources", []),
        "iterations": result.iterations,
        "tool_calls": result.tool_calls_made,
    }


async def report_generation_handler(
    params: dict,
    update_progress: Callable,
) -> dict:
    """
    Handler for report generation tasks.
    """
    from app.services.tapestry_service import generate_tapestry_report

    await update_progress(0.1, "Preparing report data...")

    store_name = params.get("store_name", "Store")
    segments = params.get("segments", [])
    location = params.get("location", "")

    await update_progress(0.3, "Generating PDF...")

    result = await generate_tapestry_report(
        store_name=store_name,
        location=location,
        segments=segments,
    )

    await update_progress(1.0, "Report complete")

    return {
        "filename": result.get("filename"),
        "filepath": result.get("filepath"),
    }


async def slide_generation_handler(
    params: dict,
    update_progress: Callable,
) -> dict:
    """
    Handler for slide generation tasks.
    """
    from app.services.slides_ai_service import generate_slides_from_prompt

    await update_progress(0.1, "Analyzing request...")

    prompt = params.get("prompt", "")
    context = params.get("context")
    theme = params.get("theme", "default")

    await update_progress(0.3, "Generating slides...")

    result = await generate_slides_from_prompt(
        prompt=prompt,
        context=context,
        theme=theme,
    )

    await update_progress(1.0, "Presentation complete")

    return {
        "filename": result.filename,
        "filepath": result.filepath,
        "slide_count": result.slide_count,
    }


async def batch_analysis_handler(
    params: dict,
    update_progress: Callable,
) -> dict:
    """
    Handler for batch location analysis.
    """
    from app.services.esri_service import get_tapestry_by_address

    locations = params.get("locations", [])
    results = []
    total = len(locations)

    for i, location in enumerate(locations):
        progress = (i + 1) / total
        await update_progress(progress, f"Analyzing location {i + 1} of {total}")

        try:
            result = await get_tapestry_by_address(
                address=location.get("address", ""),
                radius_miles=location.get("radius", 1.0),
            )
            results.append({
                "address": location.get("address"),
                "success": True,
                "data": result.to_dict() if result else None,
            })
        except Exception as e:
            results.append({
                "address": location.get("address"),
                "success": False,
                "error": str(e),
            })

    return {
        "total": total,
        "successful": sum(1 for r in results if r["success"]),
        "results": results,
    }


# =============================================================================
# Initialize Handlers
# =============================================================================

def init_task_handlers() -> None:
    """Initialize task handlers on startup."""
    task_queue.register_handler(TaskType.RESEARCH, research_task_handler)
    task_queue.register_handler(TaskType.REPORT_GENERATION, report_generation_handler)
    task_queue.register_handler(TaskType.SLIDE_GENERATION, slide_generation_handler)
    task_queue.register_handler(TaskType.BATCH_ANALYSIS, batch_analysis_handler)

    logger.info("Task handlers initialized")


# =============================================================================
# Convenience Functions
# =============================================================================

async def enqueue_research(
    query: str,
    user_id: str,
    context: Optional[dict] = None,
) -> str:
    """Enqueue a research task."""
    return await task_queue.enqueue(
        TaskType.RESEARCH,
        params={"query": query, "context": context, "user_id": user_id},
        metadata={"user_id": user_id},
    )


async def enqueue_report(
    store_name: str,
    segments: list[dict],
    location: str,
    user_id: str,
) -> str:
    """Enqueue a report generation task."""
    return await task_queue.enqueue(
        TaskType.REPORT_GENERATION,
        params={
            "store_name": store_name,
            "segments": segments,
            "location": location,
        },
        metadata={"user_id": user_id},
    )


async def enqueue_slides(
    prompt: str,
    user_id: str,
    context: Optional[dict] = None,
    theme: str = "default",
) -> str:
    """Enqueue a slide generation task."""
    return await task_queue.enqueue(
        TaskType.SLIDE_GENERATION,
        params={
            "prompt": prompt,
            "context": context,
            "theme": theme,
        },
        metadata={"user_id": user_id},
    )


async def enqueue_batch_analysis(
    locations: list[dict],
    user_id: str,
) -> str:
    """Enqueue a batch location analysis."""
    return await task_queue.enqueue(
        TaskType.BATCH_ANALYSIS,
        params={"locations": locations},
        metadata={"user_id": user_id},
    )


async def get_task_status(task_id: str) -> Optional[dict]:
    """Get task status."""
    task = await task_queue.get_task(task_id)
    return task.to_dict() if task else None
