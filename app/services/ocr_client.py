"""
OCR service wrapper for the FastAPI server.

Imports the OCRPipeline from the ocr-model directory and exposes
a simple function that accepts raw file bytes and returns a result dict.

Note: ``ocr-model/`` is added to ``sys.path`` in ``app/main.py``.
"""

import os
import re
from pathlib import Path
from typing import Optional

from ocr_pipeline import OCRPipeline, PipelineResult  # noqa: E402


# ── Module-level singleton ────────────────────────────────────────────────
_pipeline: Optional[OCRPipeline] = None


def _get_pipeline(endpoint: str, api_key: str) -> OCRPipeline:
    """Lazily initialise the OCR pipeline (one per process)."""
    global _pipeline
    if _pipeline is None:
        _pipeline = OCRPipeline(
            endpoint=endpoint,
            api_key=api_key,
            model_id="prebuilt-layout",
            high_resolution=True,
            locale="ar",
            output_format="markdown",
        )
    return _pipeline


def strip_markdown(text: str) -> str:
    """
    Remove markdown formatting so the classifier receives plain text.

    Strips:
      - Heading markers (# ## ### etc.)
      - Bold / italic markers (* ** _ __)
      - Table pipe characters and separator rows (|---|---|)
      - Horizontal rules (--- / ***)
      - Link syntax [text](url) → text
      - Image syntax ![alt](url) → alt
    """
    # Remove images ![alt](url)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Remove links [text](url)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Remove heading markers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r"(\*{1,3}|_{1,3})", "", text)
    # Remove table separator rows  |---|---|
    text = re.sub(r"^\|[\s\-:|]+\|$", "", text, flags=re.MULTILINE)
    # Remove leading/trailing pipes on table rows
    text = re.sub(r"^\|(.+)\|$", r"\1", text, flags=re.MULTILINE)
    # Remove horizontal rules
    text = re.sub(r"^(\-{3,}|\*{3,}|_{3,})$", "", text, flags=re.MULTILINE)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def run_ocr(
    file_bytes: bytes,
    filename: str,
    endpoint: str,
    api_key: str,
) -> dict:
    """
    Run the full OCR pipeline on raw file bytes.

    Returns a dict with all results (matches DocumentProcessResponse schema).
    """
    pipeline = _get_pipeline(endpoint, api_key)
    result: PipelineResult = pipeline.run_bytes(file_bytes, filename=filename)

    if not result.success:
        return {
            "success": False,
            "error": result.error or "OCR processing failed",
            "filename": filename,
        }

    # Produce plain text version for classifier
    plain_text = strip_markdown(result.cleaned_text)

    return {
        "success": True,
        "error": None,
        "filename": filename,
        "raw_text": result.raw_text,
        "cleaned_text": result.cleaned_text,
        "plain_text": plain_text,
        "primary_language": result.primary_language,
        "tables_markdown": result.tables_markdown,
        "quality": result.quality,
        "page_count": result.page_count,
        "word_count": result.word_count,
        "avg_confidence": result.avg_confidence,
        "cost_usd": result.cost_usd,
        "elapsed_seconds": result.elapsed_seconds,
        "chunks_used": result.chunks_used,
        "per_page": result.per_page,
    }
