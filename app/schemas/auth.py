from pydantic import BaseModel, Field


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
