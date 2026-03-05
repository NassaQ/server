from typing import Annotated, AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.broker import BaseBroker, RabbitMQBroker
from app.core.security import decode_token
from app.core.storage import AzureBlobStorage, StorageBase
from app.core.config import settings

from app.db.ops import UsersOps
from app.db.session import get_db
from app.models.models import Documents, Users
from app.schemas.docs import DocumentListItem

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DBSession = Annotated[AsyncSession, Depends(get_db)]
UserRepo = Annotated[UsersOps, Depends()]

TokenDep = Annotated[str, Depends(oauth2_scheme)]

def gen_username(email: str) -> str:
    local_part, domain = email.split("@")
    domain_name = domain.split(".")[0]
    return f"{local_part}_{domain_name}"

def capitalize_full_name(name: str) -> str:
    names = [n.capitalize() for n in name.split()]
    full_name = ' '.join(names)

    return full_name

def doc_to_list_item(doc: Documents) -> DocumentListItem:
    """Extract OCR status from a Documents object loaded with Processing_Status + path."""

    ocr_status = next(
        (ps for ps in doc.Processing_Status if ps.stage_name == "OCR"),
        None,
    )
    
    return DocumentListItem(
        doc_id=doc.doc_id,
        filename=doc.filename,
        path=doc.path.full_path if doc.path else "/",
        uploaded_by_user_id=doc.uploaded_by_user_id,
        uploaded_at=doc.uploaded_at,
        status=ocr_status.status if ocr_status else None,
        error_message=ocr_status.error_message if ocr_status else None,
    )

async def get_storage() -> AsyncIterator[StorageBase]:
    """
    Dependency that yields the correct storage backend based on config.
    Handles the lifecycle (opening/closing connections) automatically.
    """
    storage_type = settings.BLOB_STORAGE_TYPE
    
    storage: StorageBase
    if storage_type == "azure":
        storage = AzureBlobStorage(
            conn_str=settings.BLOB_CONNECTION_STR, 
            container=settings.BLOB_STORAGE_CONTAINER_NAME
        )
    else:
        pass

    await storage.__aenter__()
    try:
        yield storage
    finally:
        await storage.__aexit__(None, None, None)

def get_broker() -> BaseBroker:
    if settings.ENVIRONMENT == "production":
        raise NotImplementedError("Azure Bus not configured yet")
    else:
        return RabbitMQBroker(settings.MESSAGE_BROKER_URL)

def get_event_broker(request: Request) -> BaseBroker:
    return request.app.state.broker

async def get_current_user(token: TokenDep, user_repo: UserRepo) -> Users:
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
    
    user = await user_repo.get_user(user_id)

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
