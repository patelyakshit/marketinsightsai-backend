"""
Tasks API Router

Endpoints for managing background tasks.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User
from app.api.deps import get_current_user
from app.services.task_queue import (
    TaskStatus,
    TaskType,
    task_queue,
    enqueue_research,
    enqueue_report,
    enqueue_slides,
    enqueue_batch_analysis,
)

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class TaskStatusResponse(BaseModel):
    """Response with task status."""
    id: str
    task_type: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: float
    progress_message: str
    result: Optional[dict] = None
    error: Optional[str] = None


class TaskListResponse(BaseModel):
    """Response with list of tasks."""
    tasks: list[TaskStatusResponse]
    count: int


class ResearchTaskRequest(BaseModel):
    """Request to create a research task."""
    query: str = Field(..., description="Research query")
    location: Optional[str] = None
    industry: Optional[str] = None


class ReportTaskRequest(BaseModel):
    """Request to create a report task."""
    store_name: str
    location: str
    segments: list[dict]


class SlidesTaskRequest(BaseModel):
    """Request to create a slides task."""
    prompt: str
    theme: str = "default"
    context: Optional[dict] = None


class BatchAnalysisRequest(BaseModel):
    """Request for batch location analysis."""
    locations: list[dict] = Field(..., description="List of {address, radius} objects")


class TaskCreatedResponse(BaseModel):
    """Response when task is created."""
    task_id: str
    task_type: str
    status: str
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get the status of a background task.

    Poll this endpoint to check task progress and get results when complete.
    """
    task = await task_queue.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Verify ownership
    if task.metadata.get("user_id") != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this task"
        )

    return TaskStatusResponse(
        id=task.id,
        task_type=task.task_type.value,
        status=task.status.value,
        created_at=task.created_at.isoformat(),
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        progress=task.progress,
        progress_message=task.progress_message,
        result=task.result if isinstance(task.result, dict) else {"data": task.result},
        error=task.error,
    )


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    """
    List all tasks for the current user.
    """
    tasks = await task_queue.get_tasks_by_user(
        user_id=str(current_user.id),
        limit=limit,
    )

    # Apply status filter
    if status_filter:
        try:
            filter_status = TaskStatus(status_filter)
            tasks = [t for t in tasks if t.status == filter_status]
        except ValueError:
            pass  # Invalid status, ignore filter

    return TaskListResponse(
        tasks=[
            TaskStatusResponse(
                id=t.id,
                task_type=t.task_type.value,
                status=t.status.value,
                created_at=t.created_at.isoformat(),
                started_at=t.started_at.isoformat() if t.started_at else None,
                completed_at=t.completed_at.isoformat() if t.completed_at else None,
                progress=t.progress,
                progress_message=t.progress_message,
                result=t.result if isinstance(t.result, dict) else {"data": t.result} if t.result else None,
                error=t.error,
            )
            for t in tasks
        ],
        count=len(tasks),
    )


@router.delete("/{task_id}")
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Cancel a running task.
    """
    task = await task_queue.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    if task.metadata.get("user_id") != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this task"
        )

    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task in {task.status.value} status"
        )

    cancelled = await task_queue.cancel_task(task_id)

    return {
        "task_id": task_id,
        "cancelled": cancelled,
        "message": "Task cancelled" if cancelled else "Task could not be cancelled",
    }


# =============================================================================
# Task Creation Endpoints
# =============================================================================

@router.post("/research", response_model=TaskCreatedResponse)
async def create_research_task(
    request: ResearchTaskRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Create a background research task.
    """
    context = {}
    if request.location:
        context["location"] = request.location
    if request.industry:
        context["industry"] = request.industry

    task_id = await enqueue_research(
        query=request.query,
        user_id=str(current_user.id),
        context=context if context else None,
    )

    return TaskCreatedResponse(
        task_id=task_id,
        task_type=TaskType.RESEARCH.value,
        status=TaskStatus.PENDING.value,
        message="Research task created",
    )


@router.post("/report", response_model=TaskCreatedResponse)
async def create_report_task(
    request: ReportTaskRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Create a background report generation task.
    """
    task_id = await enqueue_report(
        store_name=request.store_name,
        segments=request.segments,
        location=request.location,
        user_id=str(current_user.id),
    )

    return TaskCreatedResponse(
        task_id=task_id,
        task_type=TaskType.REPORT_GENERATION.value,
        status=TaskStatus.PENDING.value,
        message="Report generation task created",
    )


@router.post("/slides", response_model=TaskCreatedResponse)
async def create_slides_task(
    request: SlidesTaskRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Create a background slide generation task.
    """
    task_id = await enqueue_slides(
        prompt=request.prompt,
        user_id=str(current_user.id),
        context=request.context,
        theme=request.theme,
    )

    return TaskCreatedResponse(
        task_id=task_id,
        task_type=TaskType.SLIDE_GENERATION.value,
        status=TaskStatus.PENDING.value,
        message="Slide generation task created",
    )


@router.post("/batch-analysis", response_model=TaskCreatedResponse)
async def create_batch_analysis_task(
    request: BatchAnalysisRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Create a background batch location analysis task.

    Analyze multiple locations in the background.
    """
    if len(request.locations) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 50 locations per batch"
        )

    task_id = await enqueue_batch_analysis(
        locations=request.locations,
        user_id=str(current_user.id),
    )

    return TaskCreatedResponse(
        task_id=task_id,
        task_type=TaskType.BATCH_ANALYSIS.value,
        status=TaskStatus.PENDING.value,
        message=f"Batch analysis task created for {len(request.locations)} locations",
    )
