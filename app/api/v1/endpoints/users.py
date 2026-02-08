from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Request, Query
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.api.deps import DBSession, AdminUser
from app.models.models import Users, Roles
from app.schemas.user import UserResponse, UserAdminUpdate

router = APIRouter()

@router.get("/", response_model=list[UserResponse], summary="List all users",
            description="Get a paginated list of all users. Requires admin role.")
async def list_users(
    db: DBSession,
    current_user: AdminUser,
    skip: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records to return")] = 20,
) -> list[UserResponse]:
    """
    List all users with pagination.

    - **skip**: Number of records to skip (default: 0)
    - **limit**: Maximum number of records to return (default: 20, max: 100)

    Requires an admin role.
    """

    query = select(Users).offset(skip).limit(limit).order_by(Users.created_at.desc())
    users = (await db.execute(query)).scalars().all()

    return users

@router.get("/pending", response_model=list[UserResponse], summary="List users pending role assignment",
            description="Get all users who haven't been assigned a role yet. Requires 'user:update' permission.",)
async def list_pending_users(
    db: DBSession,
    current_user: AdminUser,
    limit: Annotated[int, Query(ge=1, le=50, description="Max records to return")] = 20,
) -> list[UserResponse]:
    """
    List all users who are pending role assignment (role_id is NULL).
    
    - **limit**: Maximum number of records to return (default: 20, max: 50)

    Requires an admin role.
    """
    query = select(Users).options(selectinload(Users.role)).where(Users.is_active == 0).limit(limit).order_by(Users.created_at.asc())
    users = (await db.execute(query)).scalars().all()

    return users


@router.put("/{user_id}", response_model=UserResponse, summary="Update any user (admin)",
            description="Update any user's profile including role assignment.")
async def update_user(
    user_id: int,
    user_update: UserAdminUpdate,
    db: DBSession,
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

    query = select(Users).where(Users.user_id == user_id)
    user = (await db.execute(query)).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    update_data = user_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    
    conflicting_checks = []
    if user_update.email and user_update.email != user.email:
        conflicting_checks.append(Users.email == user_update.email)
    if user_update.username and user_update.username != user.username:
        conflicting_checks.append(Users.username == user_update.email)

    if conflicting_checks:
        query = select(Users).where(or_(*conflicting_checks)).where(Users.user_id != user_id)
        conflict = (await db.execute(query)).scalar_one_or_none()
        
        if conflict:
            if user_update.email and conflict.email == user_update.email:
                detail = "Email already in use"
            else:
                detail = "Username already in use"
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
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

    fields = ["email", "username", "is_active"]
    for field in fields:
        if field in update_data:
            setattr(user, field, update_data[field])
    
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, 
            detail="Update failed. Please try again."
        )
    
    return user

@router.patch("/{user_id}/activate", response_model=UserResponse, summary="Activate a user",
              description="Specifically sets a user's is_active status to True.",)
async def activate_user(user_id: int, request: Request, db: DBSession, current_user: AdminUser) -> UserResponse:
    
    body = await request.body()
    if body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is not allowed for this endpoint."
        )
    
    query = select(Users).options(selectinload(Users.role)).where(Users.user_id == user_id)
    user = (await db.execute(query)).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.is_active:
        return user

    user.is_active = True
    
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not activate user",
        )

    return user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a user",
               description="Delete a user account with the user id.")
async def delete_user(user_id: int, db: DBSession, current_user: AdminUser) -> None:
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
    
    query = select(Users).where(Users.user_id == user_id)
    user = (await db.execute(query)).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    try:
        await db.delete(user)
        await db.commit()

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete user. Please try again."
        )
