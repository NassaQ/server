from typing import Annotated
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import ActiveUser, AdminUser, DBSession
from app.models.models import VirtualPaths
from app.schemas.paths import PathCreate, PathResponse, PathUpdate

router = APIRouter()

@router.get("/", response_model=list[PathResponse], summary="Return all paths in blob storage",
            description="Get all paths in blob storage to view and return them in a tree hierarchy")
async def get_paths(
    db: DBSession,
    current_user: ActiveUser,
    minDepth: Annotated[int, Query(ge=0, le=10, description="Min depth of the paths")] = 0,
    maxDepth: Annotated[int, Query(ge=1, le=30, description="Max depth of the paths")] = 5,
    prefix: Annotated[str, Query(description="prefix of paths")] = "",
) -> list[PathResponse]:
    """
    List all paths.

    - **maxDepth**: Maximum depth of the paths to return (default: 5, max: 30)
    - **minDepth**: Minimum depth of the paths to return (default: 0, max: 10)
    - **prefix**: Prefix of the paths to return (default: '/')

    Requires an active user.
    """

    query = select(VirtualPaths).where(
        VirtualPaths.depth >= minDepth,
        VirtualPaths.depth <= maxDepth,
        VirtualPaths.full_path.startswith(prefix)
    )
    result = (await db.execute(query)).scalars().all()
    return result

@router.post("/", response_model=PathResponse, status_code=status.HTTP_201_CREATED, summary="Create new path if not exist",
             description="Create a new path if not exist, raises an exception if exists")
async def create_path(
    db: DBSession,
    current_user: AdminUser,
    path_info: PathCreate,
) -> PathResponse:
    """
    Create a new path if not exist.

    Requires an Admin user.
    """

    query = select(VirtualPaths).where(VirtualPaths.full_path == path_info.full_path)
    exists = (await db.execute(query)).scalar_one_or_none()

    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Path '{path_info.full_path}' already exists."
        )
    
    depth = len([d for d in path_info.full_path.split("/") if d])

    new_path = VirtualPaths(
        full_path=path_info.full_path,
        description=path_info.description,
        depth=depth
    )

    try:
        db.add(new_path)
        await db.commit()
        await db.refresh(new_path)
        
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, 
            detail="Creating path failed. Please try again."
        )

    return new_path

@router.patch("/{path_id}", response_model=PathResponse, summary="Update a path info",
             description="Update an existing path, raises an exception if not exist")
async def update_path(
    path_id: int,
    db: DBSession,
    current_user: AdminUser,
    path_info: PathUpdate,
) -> PathResponse:
    """
    Update an existing path.

    Requires an Admin user.
    """

    query = select(VirtualPaths).where(VirtualPaths.path_id == path_id)
    path = (await db.execute(query)).scalar_one_or_none()

    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path with id of '{path_id}' doesn't exists."
        )

    update_data = path_info.model_dump(exclude_unset=True)

    if not update_data['full_path']:
        query = select(VirtualPaths).where(VirtualPaths.full_path == path_info.full_path)
        conflict = (await db.execute(query)).scalar_one_or_none()
        
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Path '{update_data['full_path']}' already exists."
            )

    setattr(path, "full_path", update_data["full_path"])
    setattr(path, "description", update_data["description"])

    try:
        await db.commit()
        await db.refresh(path)
        
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, 
            detail="Creating path failed. Please try again."
        )

    return path

@router.delete("/{path_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a path",
             description="Delete one path if exist, raises an exception if doesn't exist")
async def delete_path(
    path_id: int,
    db: DBSession,
    current_user: AdminUser,
):
    """
    Delete a path if exists.

    Requires an Admin user.
    """

    query = select(VirtualPaths).where(VirtualPaths.path_id == path_id)
    path = (await db.execute(query)).scalar_one_or_none()

    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path with {path_id} doesn't exist"
        )
    
    try:
        await db.delete(path)
        await db.commit()
    
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete user. Please try again."
        )