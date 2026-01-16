from fastapi import APIRouter, status, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from app.models.models import Users
from app.schemas.user import UserCreate, UserResponse
from app.api.deps import DBSession, gen_username
from app.core.security import hash_password

router = APIRouter()
    
@router.post("/register", response_model=UserResponse,
    status_code=status.HTTP_201_CREATED, summary="Register a new user"
)
async def register (user_info: UserCreate, db: DBSession) -> UserResponse:
    query = select(1).where(Users.email == user_info.email)
    isEmailExist = (await db.execute(query)).first()

    if isEmailExist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    username = user_info.username or gen_username(user_info.email)
    
    query = select(1).where(Users.username == username)
    isUsernameExist = (await db.execute(query)).first() 

    if isUsernameExist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    hashed_password = hash_password(user_info.password)
    
    new_user = Users(
        username=username,
        email=user_info.email,
        password_hash=hashed_password,
        role_id=user_info.role_id,
    )

    try:
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration failed. Please try again.",
        )
    
    return UserResponse.model_validate(new_user)