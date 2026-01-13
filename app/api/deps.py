from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

DBSession = Annotated[AsyncSession, Depends(get_db)]

def gen_username(email: str) -> str:
    local_part, domain = email.split("@")
    domain_name = domain.split(".")[0]
    return f"{local_part}_{domain_name}"