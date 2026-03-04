from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession


from app.db.session import get_db
from app.models.models import Users

DBSession = Annotated[AsyncSession, Depends(get_db)]


class UsersOps:
    def __init__(self, db: DBSession):
        self.db = db

    async def get_all_users(self, skip: int, limit: int, is_active: bool | None = None) -> list[Users]:
        query = select(Users).options(selectinload(Users.role))
        
        if is_active is not None:
            query = query.where(Users.is_active == is_active)

        query = query.offset(skip).limit(limit).order_by(Users.created_at.asc())

        users = (await self.db.execute(query)).scalars().all()
        return list(users)
    
    async def get_conflict(self, user_id: int, username: str | None = None, email: str | None = None) -> bool:
        query = select(Users)
        if username:
            query = query.where(func.lower(Users.username) == username.lower())

        if email:
            query = query.where(Users.email == email.lower())
        
        exist_user = (await self.db.execute(query)).scalar_one_or_none()
        return exist_user is not None and exist_user.user_id != user_id
    
    async def conflict_exists(self, username: str | None = None, email: str | None = None) -> bool:
        query = select(1)
        if username:
            query = query.where(func.lower(Users.username) == username.lower())

        if email:
            query = query.where(Users.email == email.lower())
        
        exist_user = (await self.db.execute(query)).first()
        return exist_user is not None

        