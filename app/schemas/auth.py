from pydantic import BaseModel, Field
from datetime import datetime


class Token(BaseModel):
    """Base schema for authentication tokens"""

    token_type: str = Field(default="bearer", description="Token type")


class TokenLogin(Token):
    """Schema for response to the login endpoint"""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")


class TokenRefresh(Token):
    """Schema for response to the refresh endpoint"""

    access_token: str = Field(..., description="JWT access token")


class TokenPayload(BaseModel):
    """Schema for decoded JWT token payload."""

    sub: int = Field(..., description="Subject (user_id)")
    rid: int = Field(..., description="Role id")
    exp: datetime = Field(..., description="Expiration timestamp")
    type: str = Field(..., description="Token type: 'access' or 'refresh'")
    iat: datetime = Field(..., description="Issued at timestamp")
