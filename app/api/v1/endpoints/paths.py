from typing import Annotated
from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import ActiveUser, AdminUser, PathRepo
from app.models.models import VirtualPaths
from app.schemas.paths import PathCreate, PathResponse, PathUpdate

router = APIRouter()


@router.get("/", response_model=list[PathResponse], summary="Return all paths in blob storage",
            description="Get all paths in blob storage to view and return them in a tree hierarchy")
async def get_paths(
    path_repo: PathRepo,
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
    return await path_repo.get_all_paths(
        min_depth=minDepth, max_depth=maxDepth, prefix=prefix
    )


@router.post("/", response_model=PathResponse, status_code=status.HTTP_201_CREATED, summary="Create new path if not exist",
             description="Create a new path if not exist, raises an exception if exists")
async def create_path(
    path_repo: PathRepo,
    current_user: AdminUser,
    path_info: PathCreate,
) -> PathResponse:
    """
    Create a new path if not exist.

    Requires an Admin user.
    """
    exists = await path_repo.get_path_by_full_path(path_info.full_path)
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Path '{path_info.full_path}' already exists."
        )

    depth = len([d for d in path_info.full_path.split("/") if d])

    new_path = VirtualPaths(
        full_path=path_info.full_path,
        description=path_info.description,
        depth=depth,
    )

    try:
        return await path_repo.create_path(new_path)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{path_id}", response_model=PathResponse, summary="Update a path info",
             description="Update an existing path, raises an exception if not exist")
async def update_path(
    path_id: int,
    path_repo: PathRepo,
    current_user: AdminUser,
    path_info: PathUpdate,
) -> PathResponse:
    """
    Update an existing path.

    Requires an Admin user.
    """
    path = await path_repo.get_path(path_id)
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path with id of '{path_id}' doesn't exists."
        )

    update_data = path_info.model_dump(exclude_unset=True)

    if update_data.get("full_path"):
        conflict = await path_repo.get_path_by_full_path(update_data["full_path"])
        if conflict and conflict.path_id != path_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Path '{update_data['full_path']}' already exists."
            )

    try:
        return await path_repo.update_path(path, update_data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{path_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a path",
             description="Delete one path if exist, raises an exception if doesn't exist")
async def delete_path(
    path_id: int,
    path_repo: PathRepo,
    current_user: AdminUser,
):
    """
    Delete a path if exists.

    Requires an Admin user.
    """
    path = await path_repo.get_path(path_id)
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path with {path_id} doesn't exist"
        )

    try:
        await path_repo.delete_path(path)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
