"""
OCR service using Azure AI Document Intelligence.
"""

import io
import logging
import os
import time
from typing import Optional
from dataclasses import dataclass, field

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    DocumentAnalysisFeature,
    DocumentContentFormat,
)
from azure.core.credentials import AzureKeyCredential

logger = logging.getLogger(__name__)

# Office file types that don't support LANGUAGES / OCR_HIGH_RESOLUTION features
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"}

# Map file extensions to their correct MIME types for Azure Document Intelligence
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
}


def _is_office_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in OFFICE_EXTENSIONS


def _get_mime_type(filename: str) -> str:
    """Return the MIME type for a given filename, falling back to octet-stream."""
    _, ext = os.path.splitext(filename.lower())
    return MIME_TYPES.get(ext, "application/octet-stream")


@dataclass
class OCRResult:
    text: str = ""
    cleaned_text: str = ""
    primary_language: str = "unknown"
    tables_markdown: list[str] = field(default_factory=list)
    page_count: int = 0
    word_count: int = 0
    avg_confidence: float = 0.0
    cost_usd: float = 0.0
    elapsed_seconds: float = 0.0
    chunks_used: int = 1
    quality: dict = field(default_factory=dict)
    per_page: list[dict] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    source_file: str = ""


class OCRClient:
    PRICING = {"prebuilt-read": 0.0015, "prebuilt-layout": 0.0100}
    FEATURE_PRICING = {"ocr.highResolution": 0.0100}

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        model_id: str = "prebuilt-layout",
        high_resolution: bool = True,
        locale: Optional[str] = None,
    ):
        self.endpoint = endpoint or os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT", "")
        self.api_key = api_key or os.getenv("AZURE_DOC_INTELLIGENCE_KEY", "")
        self.model_id = model_id
        self.high_resolution = high_resolution
        self.locale = locale

        if not self.endpoint or not self.api_key:
            raise ValueError("Missing Azure Document Intelligence credentials.")

        self.client = DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_key),
        )

    def process_bytes(self, data: bytes, filename: str = "") -> OCRResult:
        start = time.time()
        try:
            features = []
            if not _is_office_file(filename):
                features.append(DocumentAnalysisFeature.LANGUAGES)
                if self.high_resolution:
                    features.append(DocumentAnalysisFeature.OCR_HIGH_RESOLUTION)

            poller = self.client.begin_analyze_document(
                model_id=self.model_id,
                body=io.BytesIO(data),
                locale=self.locale,
                features=features,
                output_content_format=DocumentContentFormat.MARKDOWN,
                content_type=_get_mime_type(filename),
            )
            result = poller.result()
            elapsed = time.time() - start
            return self._build_result(result, elapsed, filename)
        except Exception as exc:
            elapsed = time.time() - start
            logger.error("OCR processing failed for '%s': %s", filename, exc)
            return OCRResult(error=str(exc), elapsed_seconds=round(elapsed, 2))

    def _build_result(self, raw, elapsed: float, filename: str) -> OCRResult:
        api_text = raw.content or ""
        pages = []
        total_words = 0
        confidence_sum = 0.0
        confidence_count = 0

        for p in raw.pages or []:
            words = p.words or []
            total_words += len(words)
            page_conf_sum = 0.0
            page_conf_count = 0
            for w in words:
                if w.confidence is not None:
                    confidence_sum += w.confidence
                    confidence_count += 1
                    page_conf_sum += w.confidence
                    page_conf_count += 1
            page_avg_conf = (page_conf_sum / page_conf_count) if page_conf_count else 0.0
            status = "good" if page_avg_conf >= 0.7 else ("sparse" if page_avg_conf >= 0.3 else "poor")
            pages.append({
                "page_number": p.page_number,
                "words_count": len(words),
                "avg_confidence": round(page_avg_conf, 4),
                "status": status,
            })

        avg_conf = (confidence_sum / confidence_count) if confidence_count else 0.0
        page_count = len(pages)

        tables_md = []
        for t in raw.tables or []:
            grid = [["" for _ in range(t.column_count)] for _ in range(t.row_count)]
            for c in t.cells or []:
                if c.row_index < t.row_count and c.column_index < t.column_count:
                    grid[c.row_index][c.column_index] = c.content or ""
            if grid:
                header = "| " + " | ".join(grid[0]) + " |"
                sep = "| " + " | ".join(["---"] * t.column_count) + " |"
                body = ["| " + " | ".join(row) + " |" for row in grid[1:]]
                tables_md.append("\n".join([header, sep, *body]))

        detected_langs = []
        for lang in raw.languages or []:
            if lang.locale and lang.locale not in detected_langs:
                detected_langs.append(lang.locale)
        primary_lang = detected_langs[0] if detected_langs else "unknown"

        base_cost = page_count * self.PRICING.get(self.model_id, 0.01)
        feature_cost = 0.0
        if self.high_resolution:
            feature_cost += page_count * self.FEATURE_PRICING.get("ocr.highResolution", 0.0)
        cost = round(base_cost + feature_cost, 6)

        cleaned = api_text.strip()
        final_word_count = max(total_words, len(cleaned.split()))

        return OCRResult(
            text=api_text,
            cleaned_text=cleaned,
            primary_language=primary_lang,
            tables_markdown=tables_md,
            page_count=page_count,
            word_count=final_word_count,
            avg_confidence=round(avg_conf, 4),
            cost_usd=cost,
            elapsed_seconds=round(elapsed, 2),
            chunks_used=1,
            quality={"model": self.model_id, "pages": page_count},
            per_page=pages,
            success=True,
            source_file=filename,
        )


_ocr_client: Optional[OCRClient] = None


def get_ocr_client() -> OCRClient:
    global _ocr_client
    if _ocr_client is None:
        from app.core.config import settings

        _ocr_client = OCRClient(
            endpoint=settings.AZURE_DOC_INTELLIGENCE_ENDPOINT,
            api_key=settings.AZURE_DOC_INTELLIGENCE_KEY,
        )
    return _ocr_client
