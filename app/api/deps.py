from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.db.session import get_db
from app.core.security import decode_token
from app.models.models import Users

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DBSession = Annotated[AsyncSession, Depends(get_db)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]

def gen_username(email: str) -> str:
    local_part, domain = email.split("@")
    domain_name = domain.split(".")[0]
    return f"{local_part}_{domain_name}"

async def get_current_user(token: TokenDep, db: DBSession) -> Users:
    """
    Validate JWT token and return the current user.
    """

    credException = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise credException
    
    subject = payload.get("sub")
    if not subject:
        raise credException
    
    try:
        user_id = int(subject)
    except ValueError:
        raise credException
    
    query = select(Users).options(selectinload(Users.role)).where(Users.user_id == user_id)
    user = (await db.execute(query)).scalar_one_or_none()

    if not user:
        raise credException
    
    return user

CurrentUser = Annotated[Users, Depends(get_current_user)]

async def get_current_active_user(current_user: CurrentUser) -> Users:
    """
    Ensure the current user is active.
    """

    if current_user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is pending role assignment. Please contact an administrator.",
        )
    
    return current_user

ActiveUser = Annotated[Users, Depends(get_current_active_user)]

class RoleChecker:
    def __init__(self, role_id: int):
        self.role_id = role_id

    def __call__(self, user: ActiveUser) -> Users:
        if user.role_id != self.role_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to perform this action.",
            )
        return user

AdminUser = Annotated[Users, Depends(RoleChecker(role_id=99))]
