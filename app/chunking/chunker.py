"""
Semantic chunker: splits a Section into embedding-sized pieces.

Strategy:
  1. Split section content at paragraph boundaries (\n\n).
  2. Accumulate paragraphs into a chunk until the token budget is reached.
  3. When a single paragraph exceeds the budget, split it by sentences.
  4. Each chunk is prefixed with its heading context so the embedding
     captures "what section this is about" even without the neighbours.
  5. An overlap tail from the previous chunk is prepended so meaning
     doesn't break hard at boundaries.

Token counting uses tiktoken with the cl100k_base encoding (shared by
GPT-4 and text-embedding-3-* models).
"""

import re
from dataclasses import dataclass

import tiktoken

from app.config import settings
from app.parsing.markdown_parser import ParsedSection
from app.utils.logging import get_logger

logger = get_logger(__name__)

# tiktoken encoding — reuse the singleton for performance
_ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass
class ChunkData:
    chunk_index: int
    chunk_text: str
    token_count: int
    # Filled in by the ingestion pipeline after DB insertion
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_section(
    section: ParsedSection,
    max_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[ChunkData]:
    """
    Split one ParsedSection into a list of ChunkData objects.

    Args:
        section:        Parsed section to chunk.
        max_tokens:     Override settings.max_chunk_tokens.
        overlap_tokens: Override settings.chunk_overlap_tokens.

    Returns:
        Ordered list of ChunkData (chunk_index is 0-based within section).
    """
    max_tok = max_tokens or settings.max_chunk_tokens
    overlap_tok = overlap_tokens or settings.chunk_overlap_tokens

    # Build the heading prefix that is prepended to every chunk in this section.
    # This ensures the embedding captures context even without neighbouring chunks.
    heading_prefix = _build_heading_prefix(section)
    prefix_tokens = _count_tokens(heading_prefix)

    # If the prefix alone is >= max_tokens something is deeply wrong; log and proceed
    if prefix_tokens >= max_tok:
        logger.warning(
            "Heading prefix exceeds max_tokens (%d >= %d) for section '%s'",
            prefix_tokens, max_tok, section.heading,
        )

    available_tokens = max_tok - prefix_tokens
    paragraphs = _split_into_paragraphs(section.content)

    raw_chunks = _pack_paragraphs(paragraphs, available_tokens)
    result: list[ChunkData] = []
    overlap_tail = ""

    for idx, raw_text in enumerate(raw_chunks):
        # Prepend overlap from previous chunk (helps embeddings bridge boundaries)
        if overlap_tail:
            text = heading_prefix + overlap_tail + "\n\n" + raw_text
        else:
            text = heading_prefix + raw_text

        token_count = _count_tokens(text)
        result.append(ChunkData(
            chunk_index=idx,
            chunk_text=text.strip(),
            token_count=token_count,
        ))

        # Compute overlap tail for the next chunk
        overlap_tail = _extract_tail(raw_text, overlap_tok)

    return result


def count_tokens(text: str) -> int:
    """Public helper for token counting used across modules."""
    return _count_tokens(text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _build_heading_prefix(section: ParsedSection) -> str:
    """
    Returns a markdown-style heading prefix e.g.  '## Installation\n\n'
    Level 0 (root) sections have no prefix.
    """
    if not section.heading:
        return ""
    hashes = "#" * section.level
    return f"{hashes} {section.heading}\n\n"


def _split_into_paragraphs(content: str) -> list[str]:
    """
    Split by blank lines; fall back to sentence splitting for large blocks.
    """
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    result: list[str] = []
    for para in paragraphs:
        if _count_tokens(para) > settings.max_chunk_tokens:
            # Paragraph is too large — break into sentences
            result.extend(_split_by_sentences(para))
        else:
            result.append(para)
    return result


def _split_by_sentences(text: str) -> list[str]:
    """Naive sentence splitter — splits on '. ', '! ', '? '."""
    sentence_endings = re.compile(r"(?<=[.!?])\s+")
    sentences = sentence_endings.split(text)
    return [s.strip() for s in sentences if s.strip()]


def _pack_paragraphs(paragraphs: list[str], token_budget: int) -> list[str]:
    """
    Greedy bin-packing: accumulate paragraphs until the budget is exhausted,
    then start a new chunk.
    """
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _count_tokens(para)

        if current_tokens + para_tokens > token_budget and current_parts:
            chunks.append("\n\n".join(current_parts))
            current_parts = [para]
            current_tokens = para_tokens
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks if chunks else [""]


def _extract_tail(text: str, overlap_tokens: int) -> str:
    """
    Return the last `overlap_tokens` tokens of text as a plain string.
    Used to prepend overlap to the following chunk.
    """
    tokens = _ENCODING.encode(text)
    if len(tokens) <= overlap_tokens:
        return text
    tail_tokens = tokens[-overlap_tokens:]
    return _ENCODING.decode(tail_tokens)
