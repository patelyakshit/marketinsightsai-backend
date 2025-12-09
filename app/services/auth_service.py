from datetime import datetime, timedelta
import bcrypt
from jose import jwt, JWTError
from app.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes))
    to_encode = {
        "sub": user_id,
        "exp": expire,
        "type": "access"
    }
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token with longer expiry."""
    expire = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)
    to_encode = {
        "sub": user_id,
        "exp": expire,
        "type": "refresh"
    }
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT token. Returns payload or None if invalid."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        return None


def get_user_id_from_token(token: str) -> str | None:
    """Extract user ID from a valid token."""
    payload = decode_token(token)
    if payload:
        return payload.get("sub")
    return None
