from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Request, Query
from sqlalchemy import select

from app.api.deps import DBSession, UserRepo, AdminUser, ActiveUser, CurrentUser, capitalize_full_name
from app.models.models import Roles
from app.schemas.user import UserResponse, UserAdminUpdate, UserUpdate

router = APIRouter()

@router.get("/", response_model=list[UserResponse], summary="List all users",
            description="Get a paginated list of all users. Requires admin role.")
async def list_users(
    user_repo: UserRepo,
    current_user: AdminUser,
    skip: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records to return")] = 20,
    is_active: Annotated[bool | None, Query(description="filter by pending users")] = None,
) -> list[UserResponse]:
    """
    List all users with pagination.

    - **skip**: Number of records to skip (default: 0)
    - **limit**: Maximum number of records to return (default: 20, max: 100)

    Requires an admin role.
    """

    users = await user_repo.get_all_users(skip, limit, is_active)

    return users

@router.get("/me", response_model=UserResponse, summary="Get current user profile",
            description="Get the profile of the currently authenticated user.")
async def get_current_user_profile(current_user: CurrentUser) -> UserResponse:
    """
    Get the current authenticated user's profile.

    Requires a valid access token in the Authorization header.
    """
    return current_user

@router.patch("/me", response_model=UserResponse, summary="Update current user",
              description="Update current user profile data, just the personal ones")
async def update_current_user(
    user_update: UserUpdate,
    user_repo: UserRepo,
    db: DBSession,
    current_user: ActiveUser,
) -> UserResponse:
    """
    Update current user's profile.

    Allowed updates:
    - **full_name**: New full name
    - **username**: New username
    """

    update_data = user_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    
    if user_update.username and user_update.username.lower() != current_user.username.lower():
        conflict = await user_repo.get_conflict(current_user.user_id, username=user_update.username)

        if conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="username already exists",
            )
        
    if "full_name" in update_data:
        update_data["full_name"] = capitalize_full_name(update_data["full_name"])
    
    try:
        updated_user = await user_repo.update_user(current_user, update_data)
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=str(e)
        )
    
    return updated_user



@router.patch("/{user_id}", response_model=UserResponse, summary="Update any user (admin)",
            description="Update any user's profile including role assignment.")
async def update_user(
    user_id: int,
    user_update: UserAdminUpdate,
    db: DBSession,
    user_repo: UserRepo,
    current_user: AdminUser
) -> UserResponse:
    """
    Update any user's profile (Admin only).

    Allowed updates:
    - **email**: New email address
    - **username**: New username
    - **role_id**: Assign or change role
    - **is_active**: Activate or deactivate the user
    """

    user = await user_repo.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # FIXME: an admin cannot update himself throw this endpoint
    
    update_data = user_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    
    conflict = await user_repo.get_conflict(user_id, user_update.username, user_update.email)
    if conflict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already exists",
        )
    
    if user_update.role_id and user_update.role_id != user.role_id:
        query = select(Roles).where(Roles.role_id == user_update.role_id)
        role_exist = (await db.execute(query)).scalar_one_or_none()

        if not role_exist:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role with id {user_update.role_id} does not exist",
            )
        
        user.role_id = user_update.role_id

    try:
        updated_user = await user_repo.update_user(current_user, update_data)
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=str(e)
        )
    
    return updated_user

@router.patch("/{user_id}/activate", response_model=UserResponse, summary="Activate a user",
              description="Specifically sets a user's is_active status to True.",)
async def activate_user(user_id: int, request: Request, user_repo: UserRepo, current_user: AdminUser) -> UserResponse:
    
    body = await request.body()
    if body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is not allowed for this endpoint."
        )
    
    user = await user_repo.get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    try:
        user = await user_repo.activate(user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a user",
               description="Delete a user account with the user id.")
async def delete_user(user_id: int, user_repo: UserRepo, current_user: AdminUser) -> None:
    """
    Delete a user by their ID.

    Note: This will fail if the user has related records (documents, folders, etc.)
    that reference this user due to foreign key constraints.
    """

    if current_user.user_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account."
        )
    
    user = await user_repo.get_user(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    try:
        await user_repo.delete_user(user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
