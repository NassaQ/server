"""
RAG endpoints for semantic search and retrieval-augmented generation.

POST /ingest — Chunk, embed, and store a processed document
POST /search — Semantic search (Azure AI Search → Cohere rerank → results)
POST /ask — Full RAG (search → context → gpt-4.1-mini → answer)
GET /documents — List ingested documents
DELETE /documents/{id} — Remove a document from the vector store
GET /stats — Vector store statistics
"""

import asyncio

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ActiveUser, DocRepo, LogRepo, RagIngestRepo
from app.schemas.rag import (
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    AskRequest,
    AskResponse,
    DocumentInfo,
    RemoveResponse,
    StoreStatsResponse,
)
from app.services import rag
from app.services import file_storage

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    body: IngestRequest,
    doc_repo: DocRepo,
    rag_repo: RagIngestRepo,
    log_repo: LogRepo,
    user: ActiveUser = None, # type: ignore
):
    """
    Chunk, embed, and store a processed document in the vector store.

    Call this after ``POST /documents/process`` to make the document
    searchable via semantic search / RAG. Records the ingest outcome
    (chunks created, tokens used, status) in the ``Rag_Ingest`` table.
    """
    if not body.cleaned_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cleaned_text is empty — nothing to ingest",
        )

    doc = await doc_repo.get_document_by_mongo_id(body.document_id)

    result = await asyncio.to_thread(
        rag.ingest,
        document_id=body.document_id,
        cleaned_text=body.cleaned_text,
        tables_markdown=body.tables_markdown or [],
        classification=body.classification,
        language=body.language,
        source_file=body.source_file,
    )

    if doc:
        try:
            await rag_repo.record_ingest(
                doc_id=doc.doc_id,
                status=result["status"],
                chunks_count=result.get("chunks_created", 0),
                total_tokens=result.get("total_tokens", 0),
            )
        except ValueError:
            pass

        from app.models.models import ProcessingStatus
        from app.db.session import get_db as get_session
        from sqlalchemy import select

        async for session in get_session():
            query = select(ProcessingStatus).where(
                ProcessingStatus.doc_id == doc.doc_id,
                ProcessingStatus.stage_name == "Vectorization",
            )
            record = (await session.execute(query)).scalar_one_or_none()
            if record:
                from datetime import datetime, timezone
                record.status = "Finished"
                record.end_time = datetime.now(timezone.utc)
                await session.commit()

        await log_repo.write_log(
            action_type="rag_ingest",
            user_id=user.user_id if user else None,
            entity_id=doc.doc_id,
            details=f"Ingested document {body.document_id}: {result['status']}",
        )

    return IngestResponse(**result)


@router.post("/search", response_model=SearchResponse)
def search_documents(
    body: SearchRequest,
    user: ActiveUser = None, # type: ignore
):
    """
    Two-stage semantic search:
    Stage 1: Azure AI Search top-20 (broad recall via embedding similarity)
    Stage 2: Cohere Rerank v4.0 Fast → top-K (precision via cross-attention)

    Returns ranked chunks with text, source metadata, and scores.
    """
    results = rag.search(
        query=body.query,
        top_k=body.top_k,
        filter_classification=body.filter_classification,
        filter_language=body.filter_language,
        filter_document_id=body.filter_document_id,
    )

    return SearchResponse(
        query=body.query,
        results=[SearchResultItem(**r) for r in results],
        total_results=len(results),
    )


@router.post("/ask", response_model=AskResponse)
def ask_question(
    body: AskRequest,
    user: ActiveUser = None, # type: ignore
):
    """
    Full RAG pipeline: search → assemble context → gpt-4.1-mini → answer.

    The model answers based ONLY on retrieved context and cites sources.
    Responds in the same language as the question (Arabic or English).
    """
    result = rag.ask(
        query=body.query,
        top_k=body.top_k,
        filter_classification=body.filter_classification,
        filter_language=body.filter_language,
        filter_document_id=body.filter_document_id,
    )

    return AskResponse(
        answer=result["answer"],
        sources=[SearchResultItem(**s) for s in result.get("sources", [])],
        tokens_used=result.get("tokens_used", 0),
        cost_usd=result.get("cost_usd", 0.0),
    )


@router.get("/", response_model=list[DocumentInfo])
def list_ingested_documents(
    user: ActiveUser = None, # type: ignore
):
    """List all documents currently stored in the vector store."""
    docs = rag.list_documents()
    return [DocumentInfo(**d) for d in docs]


@router.delete("/doc/{document_id}", response_model=RemoveResponse)
async def remove_ingested_document(
    document_id: str,
    doc_repo: DocRepo,
    rag_repo: RagIngestRepo,
    log_repo: LogRepo,
    user: ActiveUser = None, # type: ignore
):
    """Remove a document and all its chunks from the vector store."""
    result = await asyncio.to_thread(rag.remove_document, document_id)
    if result["status"] == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found in vector store",
        )

    doc = await doc_repo.get_document_by_mongo_id(document_id)
    if doc:
        try:
            await rag_repo.delete_by_doc_id(doc.doc_id)
        except Exception:
            pass

    try:
        file_storage.delete(document_id)
    except Exception:
        pass

    await log_repo.write_log(
        action_type="rag_remove",
        user_id=user.user_id if user else None,
        details=f"Removed document {document_id} from vector store",
    )

    return RemoveResponse(**result)


@router.get("/stats", response_model=StoreStatsResponse)
def get_store_stats(
    user: ActiveUser = None, # type: ignore
):
    """Return vector store statistics (total vectors, total documents)."""
    stats = rag.store_stats()
    return StoreStatsResponse(**stats)
