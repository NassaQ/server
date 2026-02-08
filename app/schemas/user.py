from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from datetime import datetime

class UserBase(BaseModel):
    full_name: str = Field(..., min_length=6, max_length=60, description="user full name", examples=["Zyad Hossam", "Alaa Awd"])
    email: EmailStr = Field(..., max_length=50, description="unique email address", examples=["user@example.com"])
    username: str | None = Field(None, min_length=3, max_length=20, description="username")

    model_config = ConfigDict(extra="forbid")

class UserCreate(UserBase):
    password: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Password must be 8-64 chars, contains digits/special chars",
        examples=["20-Na$$aQ-26"]
    )

    @field_validator('password')
    @classmethod
    def validate_pass(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if all(c.isalnum() for c in v):
            raise ValueError("Password must contain at least one special character")
        
        return v

class UserUpdate(BaseModel):
    """Schema for user self-update (cannot change role)."""

    full_name: str | None = Field(None, min_length=6, max_length=60, description="new full name")
    email: EmailStr | None = Field(None, max_length=50, description="New email address")
    username: str | None = Field(None, min_length=3, max_length=20, description="New username")
    
class UserAdminUpdate(BaseModel):
    """Schema for admin updating any user."""

    full_name: str | None = Field(None, min_length=6, max_length=60, description="New full name")
    email: EmailStr | None = Field(None, max_length=50, description="New email address")
    username: str | None = Field(None, min_length=3, max_length=20, description="New username")
    role_id: int | None = Field(None, description="New role ID")
    is_active: bool | None = Field(None, description="New User Status")

    model_config = ConfigDict(extra="forbid")


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., description="Password in plain text")

class UserResponse(UserBase):
    """
    Public User Profile.
    """

    user_id: int
    full_name: str
    username: str
    role_id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)