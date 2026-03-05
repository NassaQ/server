from typing import Annotated

from fastapi import Depends
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
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

    async def get_user(self, user_id: int | None = None, email: str | None = None) -> Users | None:
        if not user_id and not email:
            raise ValueError("Neither email nor id provided to get the user")

        query = select(Users)
        if user_id:
            query = query.where(Users.user_id == user_id)
        if email:
            query = query.where(func.lower(Users.email) == email.lower())
        
        user = (await self.db.execute(query)).scalar_one_or_none()
        return user

    async def user_exists(self, user_id: int) -> bool:
        query = select(1).where(Users.user_id == user_id)
        exists = (await self.db.execute(query)).first()

        return exists is not None
    
    async def create_user(self, new_user: Users) -> Users:
        user_data = {
            "full_name": new_user.full_name,
            "username": new_user.username,
            "email": new_user.email,
            "password_hash": new_user.password_hash,
            "role_id": new_user.role_id,
        }

        stmt = (
            insert(Users)
            .values(**user_data)
            .returning(Users)
            .options(selectinload(Users.role))
        )

        try:
            created_user = (await self.db.execute(stmt)).scalar_one()
            await self.db.commit()
            return created_user
            
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Registration failed. Please try again.")
        
    async def update_user(self, user: Users, update_data: dict) -> Users:
        for key, value in update_data.items():
            setattr(user, key, value)
            
        try:
            await self.db.commit()
            await self.db.refresh(user)
            return user
        
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Update failed. Please try again.")
    
    async def activate(self, user: Users) -> Users:
        if user.is_active:
            return user
        
        user.is_active = True
        try:
            await self.db.commit()
            await self.db.refresh(user)
            return user
        
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Activation failed. Please try again.")
        
    async def delete_user(self, user: Users) -> None:
        try:
            await self.db.delete(user)
            await self.db.commit()
        
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Couldn't delete User")