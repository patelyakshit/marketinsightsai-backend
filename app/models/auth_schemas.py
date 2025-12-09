from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


# ============== Request Schemas ==============

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class GoogleAuthRequest(BaseModel):
    """Request containing the Google ID token from frontend."""
    credential: str  # The Google ID token from Sign In with Google


# ============== Response Schemas ==============

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    avatar_url: str | None = None
    auth_provider: str | None = "email"
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class AuthMeResponse(BaseModel):
    user: UserResponse


# ============== Saved Report Schemas ==============

class SavedReportCreate(BaseModel):
    store_name: str
    store_id: str | None = None
    goal: str
    report_url: str
    report_html: str | None = None
    team_id: str | None = None


class SavedReportResponse(BaseModel):
    id: str
    store_name: str
    store_id: str | None
    goal: str
    report_url: str
    created_at: datetime
    team_id: str | None = None

    class Config:
        from_attributes = True


class SavedReportListResponse(BaseModel):
    reports: list[SavedReportResponse]


# ============== Team Schemas ==============

class TeamCreate(BaseModel):
    name: str


class TeamResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class TeamMemberResponse(BaseModel):
    id: str
    user_id: str
    user_email: str
    user_name: str | None
    role: str
    joined_at: datetime


class TeamDetailResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    created_at: datetime
    members: list[TeamMemberResponse]

    class Config:
        from_attributes = True


class TeamInvite(BaseModel):
    email: EmailStr
    role: str = "member"


# ============== Report Template Schemas ==============

class ReportTemplateCreate(BaseModel):
    name: str
    description: str | None = None
    goal: str
    config: dict = {}
    team_id: str | None = None


class ReportTemplateResponse(BaseModel):
    id: str
    name: str
    description: str | None
    goal: str
    config: dict
    is_default: bool
    created_at: datetime
    team_id: str | None = None

    class Config:
        from_attributes = True
