from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.concurrency import run_in_threadpool

from app.models.models import Users
from app.schemas.user import UserCreate, UserResponse
from app.schemas.auth import TokenLogin, TokenRefresh
from app.api.deps import UserRepo, gen_username, capitalize_full_name, TokenDep
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
async def register (user_info: UserCreate, user_repo: UserRepo) -> UserResponse:
    isEmailExist = await user_repo.conflict_exists(email=user_info.email)
    if isEmailExist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    
    username = user_info.username or gen_username(user_info.email)
    
    isUsernameExist = await user_repo.conflict_exists(email=user_info.email)
    if isUsernameExist:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    hashed_password = await run_in_threadpool(hash_password, user_info.password)
    
    new_user = Users(
        full_name=capitalize_full_name(user_info.full_name),
        username=username,
        email=user_info.email.lower(),
        password_hash=hashed_password,
        role_id=None,
    )

    try:
        created_user = await user_repo.create_user(new_user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    return created_user


@router.post("/login", response_model=TokenLogin, summary="Login and get access token",
             description="Authenticate with email and password to receive JWT tokens.")
async def login (user_repo: UserRepo, form_data: OAuth2PasswordRequestForm = Depends()) -> TokenLogin:
    """
    Login with email and password.

    Uses OAuth2 password flow:
    - **username**: Email address (OAuth2 spec uses 'username' field)
    - **password**: User's password

    Returns:
    - **access_token**: Short-lived JWT for API access
    - **refresh_token**: Long-lived JWT for getting new access tokens
    """    
    user = await user_repo.get_user(email=form_data.username)

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
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not active right now. Please contact your administrator."
        )
    
    access_token = create_access_token(subject=user.user_id, role_id=user.role_id)
    refresh_token = create_refresh_token(subject=user.user_id)

    return TokenLogin(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer"
    )

@router.post("/refresh", response_model=TokenRefresh, summary="Refresh access token",
             description="Use a valid refresh token to get a new access token.")
async def refresh_token(token: TokenDep, user_repo: UserRepo) -> TokenRefresh:
    """
    Refresh the access token using a valid refresh token.

    - **refresh_token**: The refresh token received during login

    Returns new access and refresh tokens.
    """

    payload = decode_token(token)
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
    
    user = await user_repo.get_user(user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    new_access_token = create_access_token(subject=user.user_id, role_id=user.role_id)

    return TokenRefresh(
        access_token=new_access_token,
        token_type="bearer",
    )