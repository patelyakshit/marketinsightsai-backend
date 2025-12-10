import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.db.database import get_db
from app.middleware.rate_limit import limiter
from app.db.models import User
from app.models.auth_schemas import (
    UserRegister,
    UserLogin,
    TokenResponse,
    AuthMeResponse,
    UserResponse,
    RefreshTokenRequest,
    GoogleAuthRequest,
)
from app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.api.deps import CurrentUser
from app.config import get_settings

settings = get_settings()

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    data: UserRegister,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Register a new user account. Rate limited to 5 per minute."""
    try:
        # Check if email already exists
        result = await db.execute(select(User).where(User.email == data.email))
        existing_user = result.scalar_one_or_none()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create new user
    user = User(
        id=str(uuid.uuid4()),
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Generate tokens
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            created_at=user.created_at,
        )
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    data: UserLogin,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Login with email and password. Rate limited to 10 per minute."""
    # Find user by email
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Generate tokens
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            created_at=user.created_at,
        )
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    data: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Refresh access token using a valid refresh token. Rate limited to 30 per minute."""
    payload = decode_token(data.refresh_token)

    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    # Generate new tokens
    access_token = create_access_token(user.id)
    new_refresh_token = create_refresh_token(user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            created_at=user.created_at,
        )
    )


@router.get("/me", response_model=AuthMeResponse)
async def get_current_user_info(current_user: CurrentUser):
    """Get current authenticated user's profile."""
    return AuthMeResponse(
        user=UserResponse(
            id=current_user.id,
            email=current_user.email,
            full_name=current_user.full_name,
            avatar_url=current_user.avatar_url,
            auth_provider=current_user.auth_provider,
            created_at=current_user.created_at,
        )
    )


@router.post("/google", response_model=TokenResponse)
@limiter.limit("10/minute")
async def google_auth(
    request: Request,
    data: GoogleAuthRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Authenticate with Google Sign-In. Rate limited to 10 per minute.

    This endpoint handles both sign-in and sign-up:
    - If user exists with this Google ID, sign them in
    - If user exists with this email (but different auth), link the accounts
    - If user doesn't exist, create a new account
    """
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication is not configured"
        )

    try:
        # Verify the Google ID token
        idinfo = id_token.verify_oauth2_token(
            data.credential,
            google_requests.Request(),
            settings.google_client_id
        )

        # Get user info from the token
        google_id = idinfo.get("sub")
        email = idinfo.get("email")
        full_name = idinfo.get("name")
        avatar_url = idinfo.get("picture")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not provided by Google"
            )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google token: {str(e)}"
        )

    # Check if user exists by Google ID
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        # Check if user exists by email
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            # User exists with this email - link Google account
            user.google_id = google_id
            user.auth_provider = "google"
            if avatar_url and not user.avatar_url:
                user.avatar_url = avatar_url
            if full_name and not user.full_name:
                user.full_name = full_name
        else:
            # Create new user
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                google_id=google_id,
                full_name=full_name,
                avatar_url=avatar_url,
                auth_provider="google",
                password_hash=None,  # No password for OAuth users
            )
            db.add(user)

        await db.commit()
        await db.refresh(user)

    # Generate tokens
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            auth_provider=user.auth_provider,
            created_at=user.created_at,
        )
    )
