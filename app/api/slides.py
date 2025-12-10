"""
Slides API Router

Endpoints for AI-powered presentation generation.
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User
from app.api.deps import get_current_user

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class SlideGenerationRequest(BaseModel):
    """Request for AI-generated slides."""
    prompt: str = Field(..., description="Description of the presentation to generate")
    theme: str = Field(default="default", description="Theme: default, dark, professional, modern")
    max_slides: int = Field(default=12, ge=3, le=20, description="Maximum number of slides")

    # Optional context
    store_name: Optional[str] = None
    location: Optional[str] = None
    segments: Optional[list[dict]] = None


class TapestrySlideRequest(BaseModel):
    """Request for Tapestry analysis slides."""
    store_name: str
    location: str
    segments: list[dict]
    theme: str = Field(default="default")


class MarketingSlideRequest(BaseModel):
    """Request for marketing campaign slides."""
    campaign_name: str
    target_audience: str
    content_ideas: list[str]
    key_messages: list[str]
    channels: list[str]
    theme: str = Field(default="modern")


class SlideGenerationResponse(BaseModel):
    """Response after slide generation."""
    success: bool
    filename: str
    download_url: str
    slide_count: int
    file_size_bytes: int
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/generate", response_model=SlideGenerationResponse)
async def generate_slides(
    request: SlideGenerationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a presentation from a natural language prompt.

    The AI will structure the content into appropriate slides.
    """
    from app.services.slides_ai_service import generate_slides_from_prompt

    try:
        # Build context if provided
        context = {}
        if request.store_name:
            context["store_name"] = request.store_name
        if request.location:
            context["location"] = request.location
        if request.segments:
            context["segments"] = request.segments

        result = await generate_slides_from_prompt(
            prompt=request.prompt,
            context=context if context else None,
            theme=request.theme,
            max_slides=request.max_slides,
        )

        return SlideGenerationResponse(
            success=True,
            filename=result.filename,
            download_url=f"/api/slides/download/{result.filename}",
            slide_count=result.slide_count,
            file_size_bytes=result.file_size_bytes,
            message=f"Successfully generated {result.slide_count}-slide presentation",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate presentation: {str(e)}"
        )


@router.post("/tapestry", response_model=SlideGenerationResponse)
async def generate_tapestry_slides(
    request: TapestrySlideRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a Tapestry analysis presentation.

    Creates a professional presentation from Tapestry segment data.
    """
    from app.services.slides_service import generate_tapestry_presentation

    try:
        # Generate insights first
        from app.services.ai_service import generate_business_insights
        insights = await generate_business_insights(request.segments, request.store_name)

        result = await generate_tapestry_presentation(
            store_name=request.store_name,
            location=request.location,
            segments=request.segments,
            insights=insights,
            theme=request.theme,
        )

        return SlideGenerationResponse(
            success=True,
            filename=result.filename,
            download_url=f"/api/slides/download/{result.filename}",
            slide_count=result.slide_count,
            file_size_bytes=result.file_size_bytes,
            message=f"Tapestry presentation generated with {result.slide_count} slides",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate Tapestry presentation: {str(e)}"
        )


@router.post("/marketing", response_model=SlideGenerationResponse)
async def generate_marketing_slides(
    request: MarketingSlideRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a marketing campaign presentation.
    """
    from app.services.slides_service import generate_marketing_presentation

    try:
        result = await generate_marketing_presentation(
            campaign_name=request.campaign_name,
            target_audience=request.target_audience,
            content_ideas=request.content_ideas,
            key_messages=request.key_messages,
            channels=request.channels,
            theme=request.theme,
        )

        return SlideGenerationResponse(
            success=True,
            filename=result.filename,
            download_url=f"/api/slides/download/{result.filename}",
            slide_count=result.slide_count,
            file_size_bytes=result.file_size_bytes,
            message=f"Marketing presentation generated with {result.slide_count} slides",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate marketing presentation: {str(e)}"
        )


@router.get("/download/{filename}")
async def download_slides(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """
    Download a generated presentation file.
    """
    from app.config import get_settings
    from pathlib import Path

    settings = get_settings()
    filepath = Path(settings.reports_output_path) / filename

    if not filepath.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Presentation file not found"
        )

    # Security: ensure filename doesn't escape directory
    if ".." in filename or "/" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@router.get("/themes")
async def list_themes():
    """
    List available presentation themes.
    """
    from app.services.slides_service import THEMES

    return {
        "themes": [
            {
                "id": theme_id,
                "name": theme_id.replace("_", " ").title(),
                "colors": colors,
            }
            for theme_id, colors in THEMES.items()
        ]
    }
