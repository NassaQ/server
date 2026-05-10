"""
RAG engine — orchestrates ingest, search, and ask pipelines.

Ingestion:   OCR result → chunk → clean → embed → Pinecone
Search:      query → clean → embed → Pinecone top-K → Cohere rerank top-N
Ask:         search → assemble context → gpt-4.1-mini → answer

All three pipelines are synchronous (``def``, not ``async def``).
FastAPI runs them in a threadpool automatically so they do not block
the event loop.
"""

from datetime import datetime, timezone
from typing import Optional

from openai import OpenAI

from app.core.config import settings
from .text_processor import (
    Chunk,
    chunk_document,
    clean_for_embedding,
)
from . import embedding_client
from .vector_store import PineconeVectorStore
from . import reranker as reranker_mod


_store: Optional[PineconeVectorStore] = None
_llm_client: Optional[OpenAI] = None


def get_store() -> PineconeVectorStore:
    """Return (and lazily create) the global Pinecone vector store."""
    global _store
    if _store is None:
        _store = PineconeVectorStore(
            api_key=settings.PINECONE_API_KEY,
            index_name=settings.PINECONE_INDEX_NAME,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
    return _store


def _get_llm() -> OpenAI:
    """Return (and lazily create) the Azure OpenAI client for generation."""
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            base_url=settings.AZURE_OPENAI_ENDPOINT,
        )
    return _llm_client



def ingest(
    document_id: str,
    cleaned_text: str,
    tables_markdown: Optional[list[str]] = None,
    classification: str = "",
    language: str = "unknown",
    source_file: str = "",
) -> dict:
    """
    Chunk, embed, and store a document in the vector store.

    Args:
        document_id:      Unique identifier (UUID from processing history).
        cleaned_text:     Markdown-formatted text (``PipelineResult.cleaned_text``).
        tables_markdown:  Markdown table strings from OCR.
        classification:   Category label from classifier.
        language:         Detected language (``ar`` / ``en`` / ``mixed``).
        source_file:      Original filename.

    Returns:
        Dict with ingestion summary (``chunks_created``, ``total_tokens``, etc.).
    """
    store = get_store()

    if store.has_document(document_id):
        return {
            "document_id": document_id,
            "status": "already_ingested",
            "chunks_created": 0,
        }

    chunks: list[Chunk] = chunk_document(
        cleaned_text=cleaned_text,
        tables_markdown=tables_markdown,
        chunk_size=settings.RAG_CHUNK_SIZE,
        chunk_overlap=settings.RAG_CHUNK_OVERLAP,
    )

    if not chunks:
        return {
            "document_id": document_id,
            "status": "no_chunks",
            "chunks_created": 0,
        }

    texts = [c.text_clean for c in chunks]
    embed_endpoint = settings.AZURE_OPENAI_EMBEDDING_ENDPOINT or settings.AZURE_OPENAI_ENDPOINT
    vectors = embedding_client.embed_texts(
        texts=texts,
        api_key=settings.AZURE_OPENAI_API_KEY,
        endpoint=embed_endpoint,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )

    metadatas: list[dict] = []
    for chunk in chunks:
        metadatas.append(
            {
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "section_heading": chunk.section_heading,
                "text_clean": chunk.text_clean,
                "text_original": chunk.text_original,
                "classification": classification,
                "language": language,
                "source_file": source_file,
                "token_count": chunk.token_count,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    store.add(vectors=vectors, metadatas=metadatas, document_id=document_id)

    total_tokens = sum(c.token_count for c in chunks)

    return {
        "document_id": document_id,
        "status": "ingested",
        "chunks_created": len(chunks),
        "total_tokens": total_tokens,
        "source_file": source_file,
    }



def search(
    query: str,
    top_k: int = 5,
    filter_classification: Optional[str] = None,
    filter_language: Optional[str] = None,
    filter_document_id: Optional[str] = None,
) -> list[dict]:
    """
    Two-stage semantic search: FAISS recall → Cohere rerank.

    Args:
        query:                  Natural-language query.
        top_k:                  Number of final results to return.
        filter_classification:  Only return chunks with this label.
        filter_language:        Only return chunks with this language.
        filter_document_id:     Only return chunks from this document.

    Returns:
        List of dicts, each with chunk text, metadata, and scores.
    """
    store = get_store()
    if store.total_vectors == 0:
        return []

    clean_query = clean_for_embedding(query)
    if not clean_query.strip():
        return []

    embed_endpoint = settings.AZURE_OPENAI_EMBEDDING_ENDPOINT or settings.AZURE_OPENAI_ENDPOINT
    query_vec = embedding_client.embed_query(
        query=clean_query,
        api_key=settings.AZURE_OPENAI_API_KEY,
        endpoint=embed_endpoint,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )

    faiss_k = settings.RAG_TOP_K_RETRIEVAL
    candidates = store.search(query_vec, k=faiss_k)

    if filter_classification:
        candidates = [
            c for c in candidates if c.get("classification") == filter_classification
        ]
    if filter_language:
        candidates = [c for c in candidates if c.get("language") == filter_language]
    if filter_document_id:
        candidates = [
            c for c in candidates if c.get("document_id") == filter_document_id
        ]

    if not candidates:
        return []

    candidate_texts = [c["text_clean"] for c in candidates]

    rerank_results = reranker_mod.rerank(
        query=query,
        documents=candidate_texts,
        endpoint=settings.COHERE_RERANK_ENDPOINT,
        api_key=settings.COHERE_RERANK_API_KEY,
        model=settings.COHERE_RERANK_MODEL,
        top_n=min(top_k, len(candidates)),
    )

    # ── Fallback: if reranker returned all zeros, use Pinecone scores ──
    use_fallback = all(rr.relevance_score == 0.0 for rr in rerank_results)

    results: list[dict] = []
    for rr in rerank_results:
        candidate = candidates[rr.index]
        pinecone_score = candidate.get("score", 0.0)
        results.append(
            {
                "text": candidate["text_clean"],
                "text_original": candidate.get("text_original", ""),
                "document_id": candidate.get("document_id", ""),
                "source_file": candidate.get("source_file", ""),
                "page_number": candidate.get("page_number", 1),
                "section_heading": candidate.get("section_heading", ""),
                "classification": candidate.get("classification", ""),
                "language": candidate.get("language", ""),
                "search_score": pinecone_score,
                "rerank_score": pinecone_score if use_fallback else rr.relevance_score,
            }
        )

    return results



_SYSTEM_PROMPT = """You are a document assistant for the NassaQ archive system.
You answer questions based ONLY on the provided context excerpts.

Rules:
- If the context does not contain enough information to answer, say so explicitly.
- Cite the source file and page number when possible.
- Respond in the SAME LANGUAGE as the user's question.
- Be concise and precise."""


def ask(
    query: str,
    top_k: int = 5,
    filter_classification: Optional[str] = None,
    filter_language: Optional[str] = None,
    filter_document_id: Optional[str] = None,
) -> dict:
    """
    Full RAG pipeline: search for relevant chunks, then generate an answer.

    Returns dict with ``answer``, ``sources``, and token usage.
    """
    sources = search(
        query=query,
        top_k=top_k,
        filter_classification=filter_classification,
        filter_language=filter_language,
        filter_document_id=filter_document_id,
    )

    if not sources:
        return {
            "answer": (
                "No relevant documents found.  Please ingest documents first "
                "or try a different query."
            ),
            "sources": [],
            "tokens_used": 0,
            "cost_usd": 0.0,
        }

    context_parts: list[str] = []
    for i, src in enumerate(sources, 1):
        header = f"[{i}] Source: {src['source_file']}, Page {src['page_number']}"
        if src.get("section_heading"):
            header += f", Section: {src['section_heading']}"
        context_parts.append(f"{header}\n{src['text']}")

    context = "\n\n---\n\n".join(context_parts)

    user_message = f"Context:\n{context}\n\nQuestion: {query}"

    client = _get_llm()

    response = client.chat.completions.create(
        model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_completion_tokens=1024,
        temperature=0.3,
    )

    answer = response.choices[0].message.content or ""
    tokens_used = response.usage.total_tokens if response.usage else 0

    # Cost estimation (gpt-4.1-mini pricing)
    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0
    cost_usd = (input_tokens / 1_000_000) * 0.40 + (output_tokens / 1_000_000) * 1.60

    return {
        "answer": answer.strip(),
        "sources": sources,
        "tokens_used": tokens_used,
        "cost_usd": round(cost_usd, 6),
    }




def list_documents() -> list[dict]:
    """List all documents in the vector store."""
    return get_store().list_documents()


def remove_document(document_id: str) -> dict:
    """Remove a document and all its chunks from the vector store."""
    store = get_store()
    if not store.has_document(document_id):
        return {"document_id": document_id, "status": "not_found", "chunks_removed": 0}

    removed = store.remove_document(document_id)
    return {
        "document_id": document_id,
        "status": "removed",
        "chunks_removed": removed,
    }


def store_stats() -> dict:
    """Return vector store statistics."""
    store = get_store()
    return {
        "total_vectors": store.total_vectors,
        "total_documents": store.total_documents,
    }
