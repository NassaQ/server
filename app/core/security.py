from datetime import timedelta, datetime, timezone
from typing import Any

import bcrypt
from jose import jwt

from app.core.config import settings

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)

def create_access_token(subject: int, role_id: int, expires_delta: timedelta | None = None) -> str:
    """
    Create a JWT access token.

    Args:
        subject: The user_id to encode in the token
        role_id: The role_id of the user to be encoded
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode: dict[str, Any] = {
        "sub": str(subject),
        "rid": role_id,
        "exp": expire,
        "type": "access",
        "iat": datetime.now(timezone.utc),
    }

    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )

    return encoded_jwt

def create_refresh_token(subject: int) -> str:
    """
    Create a JWT refresh token.

    Args:
        subject: The user_id to encode in the token

    Returns:
        Encoded JWT refresh token string
    """

    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh",
        "iat": datetime.now(timezone.utc)
    }

    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt
