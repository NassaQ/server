from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class PathBase(BaseModel):
    full_path: str = Field(..., description="the full striped path")
    description: Optional[str] = Field(None, description="the description of the path")

    model_config = ConfigDict(extra="forbid")

class PathCreate(PathBase):
    """Schema for creating a new virtual path"""
    pass

class PathResponse(BaseModel):
    """
    Schema for response to get a path.
    Fields are serialized in the order they are defined here.
    """
    id: int = Field(..., validation_alias="path_id", description="the path id")
    full_path: str = Field(..., description="the full striped path")
    description: Optional[str] = Field(None, description="the description of the path")
    depth: int = Field(..., description="the depth of the hierarchy")
    created_at: datetime = Field(..., description="the created time of this path")

    model_config = ConfigDict(from_attributes=True)

class PathUpdate(BaseModel):
    full_path: Optional[str] = Field(None, description="the full striped path")
    description: Optional[str] = Field(None, description="the description of the path")

    model_config = ConfigDict(extra="forbid")
