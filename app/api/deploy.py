"""
Deploy API Router

Endpoints for one-click landing page deployment.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User
from app.api.deps import get_current_user

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class LandingPageRequest(BaseModel):
    """Request for landing page generation."""
    business_name: str = Field(..., min_length=1)
    business_description: str = Field(..., min_length=10)
    target_audience: str = Field(..., min_length=5)
    key_benefits: list[str] = Field(..., min_items=1, max_items=6)
    call_to_action: str = Field(default="Get Started")
    primary_color: str = Field(default="#155E81")
    secondary_color: str = Field(default="#36B37E")


class TapestryLandingPageRequest(BaseModel):
    """Request for landing page from Tapestry data."""
    store_name: str
    location: str
    business_type: str
    segments: list[dict]


class LandingPageResponse(BaseModel):
    """Response after landing page generation."""
    success: bool
    page_id: str
    filename: str
    preview_url: str
    download_url: str
    message: str


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/landing-page", response_model=LandingPageResponse)
async def generate_landing_page(
    request: LandingPageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a marketing landing page.

    Creates an AI-powered HTML landing page with:
    - Hero section with compelling headline
    - Features/benefits section
    - About section
    - Call-to-action section
    """
    from app.services.landing_page_service import generate_landing_page

    try:
        result = await generate_landing_page(
            business_name=request.business_name,
            business_description=request.business_description,
            target_audience=request.target_audience,
            key_benefits=request.key_benefits,
            call_to_action=request.call_to_action,
            primary_color=request.primary_color,
            secondary_color=request.secondary_color,
        )

        return LandingPageResponse(
            success=True,
            page_id=result.page_id,
            filename=result.filename,
            preview_url=f"/api/deploy/preview/{result.filename}",
            download_url=f"/api/deploy/download/{result.filename}",
            message="Landing page generated successfully",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Landing page generation failed: {str(e)}"
        )


@router.post("/landing-page/tapestry", response_model=LandingPageResponse)
async def generate_tapestry_landing_page(
    request: TapestryLandingPageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a landing page based on Tapestry segment data.

    Creates targeted messaging based on the dominant consumer segments.
    """
    from app.services.landing_page_service import generate_landing_page_from_tapestry

    try:
        result = await generate_landing_page_from_tapestry(
            store_name=request.store_name,
            location=request.location,
            segments=request.segments,
            business_type=request.business_type,
        )

        return LandingPageResponse(
            success=True,
            page_id=result.page_id,
            filename=result.filename,
            preview_url=f"/api/deploy/preview/{result.filename}",
            download_url=f"/api/deploy/download/{result.filename}",
            message="Tapestry-targeted landing page generated",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Landing page generation failed: {str(e)}"
        )


@router.get("/preview/{filename}", response_class=HTMLResponse)
async def preview_landing_page(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """
    Preview a generated landing page.
    """
    from pathlib import Path
    from app.config import get_settings

    settings = get_settings()
    filepath = Path(settings.reports_output_path) / "landing_pages" / filename

    if not filepath.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Landing page not found"
        )

    # Security check
    if ".." in filename or "/" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )

    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@router.get("/download/{filename}")
async def download_landing_page(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """
    Download a generated landing page as HTML file.
    """
    from pathlib import Path
    from app.config import get_settings

    settings = get_settings()
    filepath = Path(settings.reports_output_path) / "landing_pages" / filename

    if not filepath.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Landing page not found"
        )

    if ".." in filename or "/" in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="text/html",
    )
