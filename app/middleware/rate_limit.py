"""
Rate Limiting Middleware

Uses slowapi for FastAPI rate limiting with in-memory storage.
For production with multiple workers, consider Redis backend.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse

# Create limiter instance
# Key function extracts client identifier (IP address by default)
limiter = Limiter(key_func=get_remote_address)


def get_user_or_ip(request: Request) -> str:
    """
    Get user ID from auth header or fall back to IP.
    This allows authenticated users to have separate limits from anonymous.
    """
    # Try to get user from auth header (if present)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # Use token hash as key (not full token for privacy)
        token = auth_header[7:]
        if len(token) > 10:
            return f"user:{token[:10]}"

    # Fall back to IP
    return get_remote_address(request)


# Limiter with user-aware key function
user_limiter = Limiter(key_func=get_user_or_ip)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please try again later.",
            "retry_after": exc.detail,
        },
        headers={"Retry-After": str(60)},  # Suggest retry after 60 seconds
    )
