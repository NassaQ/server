from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.api.deps import DBSession
from app.models.models import Users, Roles
from app.schemas.user import UserResponse, UserAdminUpdate

router = APIRouter()

@router.put("/{user_id}", response_model=UserResponse, summary="Update any user (admin)",
            description="Update any user's profile including role assignment.")
async def update_user(
    user_id: int,
    user_update: UserAdminUpdate,
    db: DBSession,
) -> UserResponse:
    """
    Update any user's profile (Admin only).

    Allowed updates:
    - **email**: New email address
    - **username**: New username
    - **role_id**: Assign or change role
    - **is_active**: Activate or deactivate the user
    """

    query = select(Users).options(selectinload(Users.role)).where(Users.user_id == user_id)
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
    
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        role_id=user.role_id, # type: ignore
        created_at=user.created_at,
    )
