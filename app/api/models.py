"""
Models API Router

Endpoints for multi-model LLM support.
Allows users to select different AI models and view available options.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User
from app.api.deps import get_current_user

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class ModelInfo(BaseModel):
    """Information about an available model."""
    id: str
    name: str
    provider: str
    context_window: int
    supports_vision: bool
    recommended_for: list[str] = []


class ModelsListResponse(BaseModel):
    """Response with available models."""
    models: list[ModelInfo]
    default_model: str


class ChatRequest(BaseModel):
    """Request for chat completion with model selection."""
    messages: list[dict] = Field(..., description="Chat messages")
    model: Optional[str] = Field(None, description="Specific model ID")
    task_type: Optional[str] = Field(None, description="Task type for auto-selection: chat, analysis, creative, code, fast")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None)
    json_mode: bool = Field(default=False)
    stream: bool = Field(default=False)


class ChatResponse(BaseModel):
    """Response from chat completion."""
    content: str
    model: str
    provider: str
    usage: dict
    cost_usd: float
    latency_ms: float


class CompareRequest(BaseModel):
    """Request to compare responses from multiple models."""
    prompt: str = Field(..., min_length=1)
    models: list[str] = Field(..., min_items=2, max_items=4)
    temperature: float = Field(default=0.7)


class CompareResponse(BaseModel):
    """Response with comparisons from multiple models."""
    prompt: str
    responses: list[dict]
    total_cost_usd: float
    total_latency_ms: float


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/", response_model=ModelsListResponse)
async def list_models():
    """
    List all available AI models.

    Returns models from all configured providers (OpenAI, Anthropic, Google).
    This endpoint is public - no authentication required.
    """
    from app.services.llm_service import get_llm_service, TaskType

    llm = get_llm_service()
    available = llm.get_available_models()

    # Add recommendations
    task_recommendations = {
        "gpt-4o": ["chat", "creative", "general"],
        "gpt-4o-mini": ["fast", "simple queries"],
        "claude-3-5-sonnet": ["analysis", "code", "reasoning"],
        "claude-3-haiku": ["fast", "simple queries"],
        "gemini-2.0-flash": ["free", "large context"],
    }

    models = []
    for m in available:
        models.append(ModelInfo(
            id=m["id"],
            name=m["name"],
            provider=m["provider"],
            context_window=m["context_window"],
            supports_vision=m["supports_vision"],
            recommended_for=task_recommendations.get(m["id"], []),
        ))

    return ModelsListResponse(
        models=models,
        default_model=llm.get_model_for_task(TaskType.CHAT),
    )


@router.post("/chat", response_model=ChatResponse)
async def chat_completion(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute chat completion with model selection.

    Supports:
    - Specific model selection
    - Task-based auto-selection
    - Automatic fallback on failure
    """
    from app.services.llm_service import get_llm_service, ChatMessage, TaskType

    llm = get_llm_service()

    # Convert messages
    messages = [
        ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
        for m in request.messages
    ]

    # Convert task type
    task_type = None
    if request.task_type:
        try:
            task_type = TaskType(request.task_type)
        except ValueError:
            pass

    try:
        result = await llm.chat(
            messages=messages,
            model=request.model,
            task_type=task_type,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            json_mode=request.json_mode,
        )

        return ChatResponse(
            content=result.content,
            model=result.model,
            provider=result.provider.value,
            usage={
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
            },
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat completion failed: {str(e)}"
        )


@router.post("/compare", response_model=CompareResponse)
async def compare_models(
    request: CompareRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Compare responses from multiple models for the same prompt.

    Useful for evaluating different models' responses.
    """
    import asyncio
    from app.services.llm_service import get_llm_service, ChatMessage

    llm = get_llm_service()

    messages = [ChatMessage(role="user", content=request.prompt)]

    async def get_response(model_id: str) -> dict:
        try:
            result = await llm.chat(
                messages=messages,
                model=model_id,
                temperature=request.temperature,
                fallback=False,
            )
            return {
                "model": model_id,
                "provider": result.provider.value,
                "content": result.content,
                "tokens": result.total_tokens,
                "cost_usd": result.cost_usd,
                "latency_ms": result.latency_ms,
                "success": True,
            }
        except Exception as e:
            return {
                "model": model_id,
                "error": str(e),
                "success": False,
            }

    # Run all models in parallel
    tasks = [get_response(m) for m in request.models]
    responses = await asyncio.gather(*tasks)

    total_cost = sum(r.get("cost_usd", 0) for r in responses)
    total_latency = sum(r.get("latency_ms", 0) for r in responses)

    return CompareResponse(
        prompt=request.prompt,
        responses=responses,
        total_cost_usd=total_cost,
        total_latency_ms=total_latency,
    )


@router.get("/recommend/{task_type}")
async def recommend_model(
    task_type: str,
):
    """
    Get model recommendation for a specific task type.

    Task types:
    - chat: General conversation
    - analysis: Data analysis, reasoning
    - creative: Content generation
    - code: Code generation/analysis
    - fast: Quick responses, low latency
    """
    from app.services.llm_service import get_llm_service, TaskType, AVAILABLE_MODELS

    llm = get_llm_service()

    try:
        task = TaskType(task_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid task type. Valid types: {[t.value for t in TaskType]}"
        )

    recommended = llm.get_model_for_task(task)
    config = AVAILABLE_MODELS.get(recommended)

    return {
        "task_type": task_type,
        "recommended_model": recommended,
        "model_info": {
            "name": config.display_name if config else recommended,
            "provider": config.provider.value if config else "unknown",
            "context_window": config.context_window if config else 0,
        },
        "reasoning": {
            TaskType.CHAT: "GPT-4o provides excellent conversational abilities",
            TaskType.ANALYSIS: "Claude 3.5 Sonnet excels at complex reasoning",
            TaskType.CREATIVE: "GPT-4o is great for creative content",
            TaskType.CODE: "Claude 3.5 Sonnet is optimized for code tasks",
            TaskType.FAST: "GPT-4o-mini offers quick responses at low cost",
        }.get(task, "Selected based on availability and capabilities"),
    }
