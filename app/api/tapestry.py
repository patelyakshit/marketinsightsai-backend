"""
Tapestry API Router

Direct ArcGIS Tapestry lookup endpoints.
No file upload required - just provide an address.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User
from app.api.deps import get_current_user

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class TapestryLookupRequest(BaseModel):
    """Request for direct Tapestry lookup."""
    address: str = Field(..., description="Address to analyze")
    radius_miles: float = Field(default=1.0, ge=0.1, le=10.0, description="Trade area radius")


class TapestryCompareRequest(BaseModel):
    """Request to compare multiple locations."""
    locations: list[dict] = Field(..., description="List of locations with 'address' or 'lat'/'lon' keys")
    radius_miles: float = Field(default=1.0, ge=0.1, le=10.0)


class SegmentResponse(BaseModel):
    """Response format for a segment."""
    code: str
    name: str
    life_mode: Optional[str] = None
    percent: Optional[float] = None
    description: Optional[str] = None
    median_age: Optional[float] = None
    median_household_income: Optional[float] = None
    homeownership_rate: Optional[float] = None


class TapestryLookupResponse(BaseModel):
    """Response from Tapestry lookup."""
    success: bool
    address: str
    latitude: float
    longitude: float
    dominant_segment: Optional[SegmentResponse] = None
    all_segments: list[dict] = []
    demographics: dict = {}
    trade_area_radius_miles: float


class TapestryCompareResponse(BaseModel):
    """Response from comparing multiple locations."""
    success: bool
    locations_analyzed: int
    results: list[TapestryLookupResponse]


# =============================================================================
# Shared Helper Functions
# =============================================================================

async def _perform_tapestry_lookup(address: str, radius_miles: float) -> TapestryLookupResponse:
    """
    Shared logic for Tapestry lookup - used by both GET and POST endpoints.
    """
    from app.services.esri_service import get_tapestry_by_address

    try:
        result = await get_tapestry_by_address(
            address=address,
            radius_miles=radius_miles,
        )

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not find Tapestry data for this location"
            )

        # Format dominant segment for response
        dominant = None
        if result.dominant_segment:
            dominant = SegmentResponse(
                code=result.dominant_segment.code,
                name=result.dominant_segment.name,
                life_mode=result.dominant_segment.life_mode,
                description=result.dominant_segment.description,
                median_age=result.dominant_segment.median_age,
                median_household_income=result.dominant_segment.median_household_income,
                homeownership_rate=result.dominant_segment.homeownership_rate,
            )

        return TapestryLookupResponse(
            success=True,
            address=result.address,
            latitude=result.latitude,
            longitude=result.longitude,
            dominant_segment=dominant,
            all_segments=result.all_segments,
            demographics=result.demographics,
            trade_area_radius_miles=result.trade_area_radius_miles,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Tapestry lookup failed: {str(e)}"
        )


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/lookup", response_model=TapestryLookupResponse)
async def lookup_tapestry(
    request: TapestryLookupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get Tapestry segmentation data for an address.

    No file upload required - just provide an address and get:
    - Dominant consumer segment
    - Full segment composition
    - Demographics for the trade area
    """
    return await _perform_tapestry_lookup(request.address, request.radius_miles)


@router.get("/lookup")
async def lookup_tapestry_get(
    address: str = Query(..., description="Address to analyze"),
    radius_miles: float = Query(default=1.0, ge=0.1, le=10.0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET endpoint for Tapestry lookup (convenience method).
    """
    return await _perform_tapestry_lookup(address, radius_miles)


@router.post("/compare", response_model=TapestryCompareResponse)
async def compare_locations(
    request: TapestryCompareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Compare Tapestry data across multiple locations.

    Useful for site selection and competitive analysis.
    """
    from app.services.esri_service import get_tapestry_comparison

    if len(request.locations) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 locations per comparison"
        )

    try:
        results = await get_tapestry_comparison(
            locations=request.locations,
            radius_miles=request.radius_miles,
        )

        formatted_results = []
        for result in results:
            dominant = None
            if result.dominant_segment:
                dominant = SegmentResponse(
                    code=result.dominant_segment.code,
                    name=result.dominant_segment.name,
                    life_mode=result.dominant_segment.life_mode,
                )

            formatted_results.append(TapestryLookupResponse(
                success=True,
                address=result.address,
                latitude=result.latitude,
                longitude=result.longitude,
                dominant_segment=dominant,
                all_segments=result.all_segments,
                demographics=result.demographics,
                trade_area_radius_miles=result.trade_area_radius_miles,
            ))

        return TapestryCompareResponse(
            success=True,
            locations_analyzed=len(formatted_results),
            results=formatted_results,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Comparison failed: {str(e)}"
        )


@router.get("/segments")
async def list_segments(
    life_mode: Optional[str] = Query(None, description="Filter by LifeMode code (A-L)"),
    search: Optional[str] = Query(None, description="Search segments by name/description"),
):
    """
    List all Tapestry segments with optional filtering.
    """
    from app.services.esri_service import (
        SEGMENT_PROFILES,
        get_segments_by_lifemode,
        search_segments_by_name,
        SegmentProfile,
    )

    if search:
        segments = search_segments_by_name(search, limit=20)
        return {
            "query": search,
            "count": len(segments),
            "segments": [
                {
                    "code": s.code,
                    "name": s.name,
                    "life_mode": s.life_mode,
                    "description": s.description[:200] + "..." if len(s.description) > 200 else s.description,
                }
                for s in segments
            ]
        }

    if life_mode:
        segments = get_segments_by_lifemode(life_mode)
        return {
            "life_mode_code": life_mode.upper(),
            "count": len(segments),
            "segments": [
                {
                    "code": s.code,
                    "name": s.name,
                    "description": s.description[:200] + "..." if len(s.description) > 200 else s.description,
                }
                for s in segments
            ]
        }

    # Return all segments grouped by LifeMode
    life_modes = {}
    for code, data in SEGMENT_PROFILES.items():
        lm = data["life_mode"]
        if lm not in life_modes:
            life_modes[lm] = []
        life_modes[lm].append({
            "code": code,
            "name": data["name"],
        })

    return {
        "total_segments": len(SEGMENT_PROFILES),
        "life_modes": life_modes,
    }


@router.get("/segment/{code}")
async def get_segment_detail(code: str):
    """
    Get detailed information about a specific Tapestry segment.
    """
    from app.services.esri_service import get_segment_profile

    profile = get_segment_profile(code)

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Segment {code} not found"
        )

    return {
        "code": profile.code,
        "number": profile.number,
        "name": profile.name,
        "life_mode": profile.life_mode,
        "life_mode_code": profile.life_mode_code,
        "description": profile.description,
        "demographics": {
            "median_age": profile.median_age,
            "median_household_income": profile.median_household_income,
            "median_net_worth": profile.median_net_worth,
            "median_home_value": profile.median_home_value,
            "homeownership_rate": profile.homeownership_rate,
            "bachelors_degree_rate": profile.bachelors_degree_rate,
        }
    }
