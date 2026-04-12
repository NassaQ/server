"""
Text processing for RAG: structure-aware chunking and embedding-ready cleaning.

This module handles the critical gap between OCR output (markdown-formatted text)
and embedding input (clean, normalized plain text).

Key principle: use markdown structure for chunking FIRST, then strip markdown
BEFORE embedding.  Heading markers serve as split points; they must NOT be
removed until after the split has happened.

Why this matters:
  - Embedding raw markdown pollutes the vector space with structural tokens
    (#, |, ---, **) that carry zero semantic meaning
  - Tables in pipe format lose column-header relationships
  - Arabic diacritics cause the same word to produce different vectors
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# ── Arabic-specific patterns ─────────────────────────────────────────────
_ARABIC_DIACRITICS = re.compile("[\u0617-\u061a\u064b-\u0652\u0656-\u065f\u0670]")
_KASHIDA = "\u0640"
_BIDI_CONTROLS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")

# ── Markdown patterns ────────────────────────────────────────────────────
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BOLD_ITALIC_RE = re.compile(r"(\*{1,3}|_{1,3})")
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$", re.MULTILINE)
_HR_RE = re.compile(r"^(\-{3,}|\*{3,}|_{3,})$", re.MULTILINE)
_OCR_ARTIFACT_RE = re.compile(r"<!--.*?-->|[☐☑✓✗✘]{2,}|\.{5,}|_{5,}")

# ── HTML / OCR junk patterns ─────────────────────────────────────────────
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")  # <figure>, </figure>, <div>, etc.
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)  # multi-line HTML comments too
_ISOLATED_SHORT_LINE_RE = re.compile(  # lone 1-2 char lines (OCR image noise)
    r"^.{1,2}$", re.MULTILINE
)


# ── Data classes ─────────────────────────────────────────────────────────
@dataclass
class Chunk:
    """A single chunk of document text ready for embedding."""

    text_original: str  # Original markdown text (for traceability)
    text_clean: str = ""  # Cleaned text for embedding + display
    chunk_index: int = 0  # Position within document
    page_number: int = 1  # Approximate page number
    section_heading: str = ""  # Nearest heading (if any)
    token_count: int = 0  # Estimated token count


# ── Token estimation ─────────────────────────────────────────────────────
def _estimate_tokens(text: str) -> int:
    """
    Estimate token count without importing tiktoken (for speed).

    Approximation: ~4 chars/token for English, ~2 chars/token for Arabic.
    Uses ~3 chars/token as a middle ground for mixed content.
    """
    if not text:
        return 0
    return max(1, len(text) // 3)


# ── Cleaning ─────────────────────────────────────────────────────────────
def clean_for_embedding(text: str) -> str:
    """
    Clean text for embedding.  Removes markdown syntax, normalises Arabic,
    strips diacritics.

    This is intentionally stricter than ``strip_markdown()`` in ocr_client.py
    (which was designed for the classifier).  Differences:

    * Diacritics are ALWAYS removed (they split the embedding space)
    * OCR artifacts (checkbox symbols, dot leaders) are removed
    * Arabic punctuation is normalised to ASCII equivalents
    """
    if not text:
        return ""

    # Unicode NFC
    text = unicodedata.normalize("NFC", text)

    # ── Strip HTML tags & comments (OCR outputs <figure>, <!-- PageBreak --> etc.)
    text = _HTML_COMMENT_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)

    # ── Strip markdown ────────────────────────────────────────────────
    text = _IMAGE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = _BOLD_ITALIC_RE.sub("", text)
    text = _TABLE_SEP_RE.sub("", text)
    text = re.sub(r"^\|(.+)\|$", r"\1", text, flags=re.MULTILINE)
    text = _HR_RE.sub("", text)

    # ── OCR artifact removal ──────────────────────────────────────────
    text = _OCR_ARTIFACT_RE.sub("", text)

    # ── Remove isolated short lines (1-2 char OCR noise from images) ──
    text = _ISOLATED_SHORT_LINE_RE.sub("", text)

    # ── Arabic normalisation ──────────────────────────────────────────
    text = _ARABIC_DIACRITICS.sub("", text)  # Remove tashkeel
    text = text.replace(_KASHIDA, "")  # Remove tatweel
    text = _BIDI_CONTROLS.sub("", text)  # Remove bidi marks

    # Normalise Arabic punctuation → ASCII
    text = text.replace("\u060c", ",")  # Arabic comma
    text = text.replace("\u061b", ";")  # Arabic semicolon
    text = text.replace("\u061f", "?")  # Arabic question mark

    # ── Whitespace normalisation ──────────────────────────────────────
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


# ── Section splitting ────────────────────────────────────────────────────
def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """
    Split markdown text into sections using heading markers as boundaries.

    Returns list of ``(heading, body)`` tuples.  The heading is the text
    after the ``#`` markers (e.g. ``"Introduction"``), and the body is
    everything until the next heading (or end of text).
    """
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            # Flush previous section
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_heading, body))
            current_heading = m.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Flush last section
    body = "\n".join(current_lines).strip()
    if body:
        sections.append((current_heading, body))

    # Fallback: no headings found
    if not sections and text.strip():
        sections = [("", text.strip())]

    return sections


# ── Oversized splitting ──────────────────────────────────────────────────
def _split_oversized(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """
    Split text that exceeds *max_tokens* using paragraph then sentence
    boundaries, with optional overlap.
    """
    if _estimate_tokens(text) <= max_tokens:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)

    chunks: list[str] = []
    current_parts: list[str] = []
    current_size = 0

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)

        # If adding this paragraph exceeds the limit, flush
        if current_size + para_tokens > max_tokens and current_parts:
            chunks.append("\n\n".join(current_parts))
            # Overlap: carry the last paragraph forward if it fits
            if overlap_tokens > 0 and current_parts:
                last = current_parts[-1]
                if _estimate_tokens(last) <= overlap_tokens:
                    current_parts = [last]
                    current_size = _estimate_tokens(last)
                else:
                    current_parts = []
                    current_size = 0
            else:
                current_parts = []
                current_size = 0

        # Paragraph itself too large → split on sentences
        if para_tokens > max_tokens:
            sentences = re.split(r"(?<=[.!?\u061f\u060c])\s+", para)
            for sent in sentences:
                sent_tokens = _estimate_tokens(sent)
                if current_size + sent_tokens > max_tokens and current_parts:
                    chunks.append("\n\n".join(current_parts))
                    current_parts = []
                    current_size = 0
                current_parts.append(sent)
                current_size += sent_tokens
        else:
            current_parts.append(para)
            current_size += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks if chunks else [text]


# ── Table linearisation ──────────────────────────────────────────────────
def _linearise_table(table_markdown: str) -> str:
    """
    Convert a markdown table to linearised text that preserves
    column–header relationships.

    ``|Name|Title|`` + ``|Ahmed|Chairman|``  →  ``Name: Ahmed, Title: Chairman``

    This representation embeds much better than raw pipe-delimited format.
    """
    lines = table_markdown.strip().split("\n")
    headers: list[str] = []
    data_rows: list[list[str]] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip separator rows
        if re.match(r"^\|[\s\-:|]+\|$", line):
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line[1:-1].split("|")]
            if not headers:
                headers = cells
            else:
                data_rows.append(cells)

    if not headers:
        # Fallback: just strip pipes
        return re.sub(r"[|]", " ", table_markdown).strip()

    linearised_parts: list[str] = []
    for row in data_rows:
        pairs: list[str] = []
        for i, cell in enumerate(row):
            header = headers[i] if i < len(headers) else f"col{i + 1}"
            if cell.strip():
                pairs.append(f"{header}: {cell}")
        if pairs:
            linearised_parts.append(", ".join(pairs))

    return ". ".join(linearised_parts) if linearised_parts else table_markdown


# ── Main chunking function ───────────────────────────────────────────────
def chunk_document(
    cleaned_text: str,
    tables_markdown: Optional[list[str]] = None,
    chunk_size: int = 400,
    chunk_overlap: int = 50,
    min_chunk_size: int = 30,
) -> list[Chunk]:
    """
    Split a document into chunks optimised for embedding.

    Strategy (in order):
      1. Split on heading markers to create semantic sections
      2. Within each section, split on paragraph boundaries if oversized
      3. Discard fragments smaller than *min_chunk_size* tokens
      4. Process each markdown table as a separate linearised chunk

    Args:
        cleaned_text:     Markdown-formatted text from OCR
                          (``PipelineResult.cleaned_text``).
        tables_markdown:  List of table markdown strings from OCR.
        chunk_size:       Target chunk size in estimated tokens.
        chunk_overlap:    Overlap between chunks in estimated tokens.
        min_chunk_size:   Minimum chunk size; smaller fragments are discarded.

    Returns:
        List of :class:`Chunk` objects with both original and cleaned text.
    """
    chunks: list[Chunk] = []
    idx = 0

    # ── Text chunks ───────────────────────────────────────────────────
    sections = _split_into_sections(cleaned_text)

    for heading, body in sections:
        sub_chunks = _split_oversized(body, chunk_size, chunk_overlap)

        for text in sub_chunks:
            if _estimate_tokens(text) < min_chunk_size:
                continue

            clean = clean_for_embedding(text)
            if not clean.strip():
                continue

            chunks.append(
                Chunk(
                    text_original=text,
                    text_clean=clean,
                    chunk_index=idx,
                    section_heading=heading,
                    token_count=_estimate_tokens(clean),
                )
            )
            idx += 1

    # ── Table chunks ──────────────────────────────────────────────────
    if tables_markdown:
        for table_md in tables_markdown:
            linearised = _linearise_table(table_md)
            clean = clean_for_embedding(linearised)
            if not clean.strip() or _estimate_tokens(clean) < min_chunk_size:
                continue

            chunks.append(
                Chunk(
                    text_original=table_md,
                    text_clean=clean,
                    chunk_index=idx,
                    section_heading="[Table]",
                    token_count=_estimate_tokens(clean),
                )
            )
            idx += 1

    return chunks
