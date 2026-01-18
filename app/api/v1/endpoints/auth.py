from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from app.models.models import Users
from app.schemas.user import UserCreate, UserResponse
from app.schemas.auth import Token, RefreshTokenRequest
from app.api.deps import DBSession, gen_username
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)

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

@router.post("/login", response_model=Token, summary="Login and get access token",
             description="Authenticate with email and password to receive JWT tokens.")
async def login (db: DBSession, form_data: OAuth2PasswordRequestForm = Depends()) -> Token:
    """
    Login with email and password.

    Uses OAuth2 password flow:
    - **username**: Email address (OAuth2 spec uses 'username' field)
    - **password**: User's password

    Returns:
    - **access_token**: Short-lived JWT for API access
    - **refresh_token**: Long-lived JWT for getting new access tokens
    """    
    query = select(Users).where(Users.email == form_data.username)
    user = (await db.execute(query)).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(subject=user.user_id, role_id=user.role_id)
    refresh_token = create_refresh_token(subject=user.user_id)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer"
    )

@router.post("/refresh", response_model=Token, summary="Refresh access token",
             description="Use a valid refresh token to get a new access token.")
async def refresh_token(token_request: RefreshTokenRequest, db: DBSession) -> Token:
    """
    Refresh the access token using a valid refresh token.

    - **refresh_token**: The refresh token received during login

    Returns new access and refresh tokens.
    """

    payload = decode_token(token_request.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    token_type = payload.get("type")
    if token_type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Refresh token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(subject)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    query = select(Users).where(Users.user_id == user_id)
    user = (await db.execute(query)).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    new_access_token = create_access_token(subject=user.user_id, role_id=user.role_id)
    new_refresh_token = create_refresh_token(subject=user.user_id)

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )