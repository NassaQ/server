from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession


from app.db.session import get_db
from app.models.models import (
    Documents,
    Logs,
    OcrResult,
    ProcessingStatus,
    RagIngest,
    Users,
    VirtualPaths,
)

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
        if not username and not email:
            return False
        query = select(Users)
        if username:
            query = query.where(func.lower(Users.username) == username.lower())

        if email:
            query = query.where(Users.email == email.lower())

        exist_user = (await self.db.execute(query)).scalars().first()
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

        query = select(Users).options(selectinload(Users.role))
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
            return await self.get_user(user_id=user.user_id) # type: ignore[return-value]

        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Update failed. Please try again.")

    async def activate(self, user: Users) -> Users:
        if user.is_active:
            return user

        user.is_active = True
        try:
            await self.db.commit()
            return await self.get_user(user_id=user.user_id) # type: ignore[return-value]

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


class VirtualPathsOps:
    """Data-access layer for the Virtual_Paths table."""

    def __init__(self, db: DBSession):
        self.db = db

    async def get_all_paths(
        self, min_depth: int = 0, max_depth: int = 5, prefix: str = ""
    ) -> list[VirtualPaths]:
        query = select(VirtualPaths).where(
            VirtualPaths.depth >= min_depth,
            VirtualPaths.depth <= max_depth,
            VirtualPaths.full_path.startswith(prefix),
        )
        result = (await self.db.execute(query)).scalars().all()
        return list(result)

    async def get_path(self, path_id: int) -> VirtualPaths | None:
        query = select(VirtualPaths).where(VirtualPaths.path_id == path_id)
        return (await self.db.execute(query)).scalar_one_or_none()

    async def get_path_by_full_path(self, full_path: str) -> VirtualPaths | None:
        query = select(VirtualPaths).where(VirtualPaths.full_path == full_path)
        return (await self.db.execute(query)).scalar_one_or_none()

    async def create_path(self, new_path: VirtualPaths) -> VirtualPaths:
        try:
            self.db.add(new_path)
            await self.db.commit()
            await self.db.refresh(new_path)
            return new_path
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Creating path failed. Please try again.")

    async def update_path(self, path: VirtualPaths, update_data: dict) -> VirtualPaths:
        for key, value in update_data.items():
            setattr(path, key, value)

        try:
            await self.db.commit()
            await self.db.refresh(path)
            return path
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Updating path failed. Please try again.")

    async def delete_path(self, path: VirtualPaths) -> None:
        try:
            await self.db.delete(path)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Cannot delete path. Please try again.")


class DocumentsOps:
    """Data-access layer for the Documents and Processing_Status tables."""

    def __init__(self, db: DBSession):
        self.db = db

    async def get_documents(
        self,
        skip: int = 0,
        limit: int = 20,
        status_filter: Literal["Finished", "Failed", "Processing", "Queued"] | None = None,
        user_id: int | None = None,
    ) -> tuple[int, list[Documents]]:
        """Return (total_count, page_of_documents) with optional filters."""
        conditions = []
        if user_id:
            conditions.append(Documents.uploaded_by_user_id == user_id)
        if status_filter:
            conditions.append(
                Documents.Processing_Status.any(
                    (ProcessingStatus.status == status_filter)
                    & (ProcessingStatus.stage_name == "OCR")
                )
            )

        count_query = select(func.count(Documents.doc_id))
        for cond in conditions:
            count_query = count_query.where(cond)
        total = (await self.db.execute(count_query)).scalar_one()

        query = (
            select(Documents)
            .options(
                selectinload(Documents.Processing_Status),
                selectinload(Documents.path),
            )
            .order_by(Documents.uploaded_at.desc())
            .offset(skip)
            .limit(limit)
        )
        for cond in conditions:
            query = query.where(cond)

        docs = (await self.db.execute(query)).scalars().all()
        return total, list(docs)

    async def get_document(self, doc_id: int) -> Documents | None:
        query = (
            select(Documents)
            .options(
                joinedload(Documents.path),
                selectinload(Documents.Processing_Status),
            )
            .where(Documents.doc_id == doc_id)
        )
        return (await self.db.execute(query)).scalar_one_or_none()

    async def get_document_by_mongo_id(self, mongo_doc_id: str) -> Documents | None:
        query = select(Documents).where(Documents.mongo_doc_id == mongo_doc_id)
        return (await self.db.execute(query)).scalar_one_or_none()

    async def get_document_status(
        self, doc_id: int, user_id: int | None = None
    ) -> list[tuple[Documents, ProcessingStatus]]:
        """Return list of (document, processing_status) rows for all stages."""
        query = (
            select(Documents, ProcessingStatus)
            .outerjoin(
                ProcessingStatus,
                Documents.doc_id == ProcessingStatus.doc_id,
            )
            .where(Documents.doc_id == doc_id)
        )
        if user_id is not None:
            query = query.where(Documents.uploaded_by_user_id == user_id)

        rows = (await self.db.execute(query)).all()
        return list(rows)

    async def get_active_status(self, doc_id: int) -> str | None:
        """Return the first 'Processing' stage status, or None if all stages are finished.
        
        Only blocks deletion for actively processing documents, not ones that are
        merely queued (e.g. Vectorization stuck on "Queued").
        """
        query = select(ProcessingStatus.status).where(
            ProcessingStatus.doc_id == doc_id,
            ProcessingStatus.status == "Processing",
        )
        return (await self.db.execute(query)).scalar_one_or_none()

    async def create_document(
        self, doc: Documents, processing_statuses: list[ProcessingStatus]
    ) -> Documents:
        """Insert a document and its initial processing statuses in one transaction."""
        try:
            self.db.add(doc)
            await self.db.flush()

            for ps in processing_statuses:
                ps.doc_id = doc.doc_id
                self.db.add(ps)
            await self.db.flush()
            return doc
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("A document with this filename already exists at the specified path.")

    async def commit_and_refresh(self, doc: Documents) -> Documents:
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def rollback(self) -> None:
        await self.db.rollback()

    async def delete_document(self, doc: Documents) -> None:
        """Delete a document and all its processing statuses, RAG ingest records, and OCR results."""
        try:
            await self.db.execute(
                delete(RagIngest).where(RagIngest.doc_id == doc.doc_id)
            )
            await self.db.execute(
                delete(OcrResult).where(OcrResult.doc_id == doc.doc_id)
            )
            await self.db.execute(
                delete(ProcessingStatus).where(ProcessingStatus.doc_id == doc.doc_id)
            )
            await self.db.delete(doc)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Delete failed. Please try again.")
        except Exception:
            await self.db.rollback()
            raise ValueError("An unexpected error occurred during deletion. Please try again.")


class RagIngestOps:
    """Data-access layer for the Rag_Ingest table."""

    def __init__(self, db: DBSession):
        self.db = db

    async def record_ingest(
        self,
        doc_id: int,
        status: str,
        chunks_count: int = 0,
        total_tokens: int = 0,
        error_message: str | None = None,
    ) -> RagIngest:
        """Create a new RAG ingest record for a document."""
        record = RagIngest(
            doc_id=doc_id,
            status=status,
            chunks_count=chunks_count,
            total_tokens=total_tokens,
            error_message=error_message,
        )
        try:
            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)
            return record
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Failed to record RAG ingest status.")

    async def get_by_doc_id(self, doc_id: int) -> RagIngest | None:
        query = (
            select(RagIngest)
            .where(RagIngest.doc_id == doc_id)
            .order_by(RagIngest.ingested_at.desc())
        )
        return (await self.db.execute(query)).scalar_one_or_none()

    async def delete_by_doc_id(self, doc_id: int) -> int:
        """Delete all ingest records for a document. Returns count removed."""
        result = await self.db.execute(
            delete(RagIngest).where(RagIngest.doc_id == doc_id)
        )
        await self.db.commit()
        return result.rowcount # type: ignore[return-value]


class OcrResultOps:
    """Data-access layer for the Ocr_Results table."""

    def __init__(self, db: DBSession):
        self.db = db

    async def get_by_doc_id(self, doc_id: int) -> OcrResult | None:
        query = (
            select(OcrResult)
            .where(OcrResult.doc_id == doc_id)
            .order_by(OcrResult.processed_at.desc())
        )
        return (await self.db.execute(query)).scalar_one_or_none()


class LogsOps:
    """Data-access layer for the Logs table."""

    def __init__(self, db: DBSession):
        self.db = db

    async def write_log(
        self,
        action_type: str,
        user_id: int | None = None,
        entity_id: int | None = None,
        details: str | None = None,
    ) -> None:
        log = Logs(
            action_type=action_type,
            user_id=user_id,
            entity_id=entity_id,
            details=details,
        )
        try:
            self.db.add(log)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
