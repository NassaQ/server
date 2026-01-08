from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator, UUID4
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr = Field(..., description="unique email address", examples=["user@example.com"])
    full_name: str = Field(..., min_length=3, max_length=100, description="full legal name")
    org_name: Optional[str] = Field(None, max_length=100, description="name of the user's organization")

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
        if not any(c.isalnum() for c in v):
            raise ValueError("Password must contain at least one special character")
        
        return v
    
class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., description="Password in plain text")

class UserResponse(UserBase):
    """
    Public User Profile.
    """

    id: UUID4
    role: str
    org_id: Optional[UUID4] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)