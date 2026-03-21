"""
Ingestion pipeline: orchestrates the full ingest workflow.

Steps per file:
  1. Read raw markdown from disk.
  2. Parse into ParsedDocument (sections + assets).
  3. Store full Document record.
  4. Store Section records.
  5. Chunk each section → ChunkData list.
  6. Batch-embed all chunks via OpenAI.
  7. Store Chunk records with embeddings + linked-list pointers.
  8. Store Asset records.

The pipeline is async throughout.  Embedding batches are collected
across all sections of all files to maximise API throughput.

Error handling: if a single file fails, we log and continue so one
corrupt page doesn't abort the entire ingestion run.
"""

import hashlib
import logging
import uuid
from pathlib import Path

import boto3
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking.chunker import ChunkData, chunk_section
from app.config import settings
from app.embeddings.embedder import embed_texts
from app.ingestion.cloner import (
    clone_or_pull,
    get_file_commit_hash,
    list_markdown_files,
)
from app.ingestion.detector import delete_document_by_path, detect_changed_files
from app.models.db_models import Asset, Chunk, Document, Section
from app.parsing.markdown_parser import ParsedDocument, parse_markdown_file
from app.parsing.docx_parser import parse_docx_file

logger = logging.getLogger(__name__)

# Sentinel: distinguishes "caller didn't pass commit_hash → compute from git"
# from "caller explicitly passed None → no git repo available, store NULL".
_UNSET = object()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_ingestion(
    db: AsyncSession,
    repo_url: str = "",
    force_all: bool = False,
    local_path_override: str = "",
) -> dict:
    """
    Full ingestion run for a wiki repository.

    Args:
        db:                 Async DB session (caller commits / rolls back).
        repo_url:           Git URL of the wiki to ingest (used when cloning).
        force_all:          Re-ingest every file regardless of change detection.
        local_path_override: Use this local folder directly instead of cloning.

    Returns:
        Summary dict with counts of processed, skipped, and failed files.
    """
    # Determine the repo identifier used as the DB key
    repo_key = local_path_override or repo_url
    logger.info("Starting ingestion for: %s (force_all=%s)", repo_key, force_all)

    # Step 1 — Resolve local path
    if local_path_override:
        local_path = Path(local_path_override)
        if not local_path.exists():
            raise ValueError(f"Pasta local não encontrada: {local_path_override}")
        logger.info("Usando pasta local: %s", local_path)
    else:
        local_path, _head_commit = clone_or_pull(repo_url)

    repo_url = repo_key  # use consistent key throughout

    # Step 2 — Enumerate .md files
    md_files = list_markdown_files(local_path)
    if not md_files:
        logger.warning("No markdown files found in %s", local_path)
        return {"processed": 0, "skipped": 0, "failed": 0, "total": 0}

    # Step 3 — Change detection
    changed_files, unchanged_files = await detect_changed_files(
        db, repo_url, local_path, md_files, force_all=force_all
    )

    stats = {"processed": 0, "skipped": len(unchanged_files), "failed": 0, "total": len(md_files)}

    # Step 4 — Ingest each changed file, commit per file for durability
    for rel_path in changed_files:
        try:
            await _ingest_file(db, repo_url, local_path, rel_path)
            await db.commit()  # commit per file — dados visíveis imediatamente
            stats["processed"] += 1
            logger.info("Ingested [%d/%d]: %s", stats["processed"], len(changed_files), rel_path)
        except Exception as exc:
            await db.rollback()
            stats["failed"] += 1
            logger.error("Failed to ingest %s: %s", rel_path, exc, exc_info=True)

    logger.info(
        "Ingestion complete — processed=%d skipped=%d failed=%d",
        stats["processed"], stats["skipped"], stats["failed"],
    )
    return stats


# ---------------------------------------------------------------------------
# File-level ingestion
# ---------------------------------------------------------------------------

async def _ingest_file(
    db: AsyncSession,
    repo_url: str,
    local_path: Path,
    rel_path: Path,
    commit_hash: object = _UNSET,
) -> None:
    """Ingest (or re-ingest) a single file. Deletes any existing record first.

    commit_hash:
      _UNSET (default) — compute from git (used by run_ingestion with a real repo).
      None             — no git repo available (worker flow); stored as NULL.
      str              — use the provided hash directly (passed via SQS message).
    """
    path_str = str(rel_path).replace("\\", "/")
    abs_path = local_path / rel_path

    if commit_hash is _UNSET:
        commit_hash = get_file_commit_hash(local_path, rel_path)

    await delete_document_by_path(db, repo_url, path_str)
    parsed = _parse_file(abs_path, path_str)
    document = await _store_document(db, repo_url, path_str, parsed, commit_hash)
    all_chunks, all_chunk_texts = await _store_sections_and_chunks(db, document, parsed)
    await _embed_and_assign(all_chunks, all_chunk_texts, path_str)
    _store_assets(db, document, parsed)


def _parse_file(abs_path: Path, path_str: str) -> ParsedDocument:
    """Route file to the correct parser based on its extension."""
    if abs_path.suffix.lower() == ".docx":
        return parse_docx_file(path_str, abs_path.read_bytes())
    raw_markdown = abs_path.read_text(encoding="utf-8", errors="replace")
    return parse_markdown_file(path_str, raw_markdown)


def _upload_content_to_s3(repo_url: str, path_str: str, content: str) -> str | None:
    """Upload raw document content to S3. Returns the S3 key, or None if not configured."""
    if not settings.s3_bucket:
        return None
    try:
        repo_hash = hashlib.sha256(repo_url.encode()).hexdigest()[:12]
        safe_path = path_str.replace("\\", "/").lstrip("/")
        s3_key = f"documents/{repo_hash}/{safe_path}"
        boto3.client("s3", region_name=settings.aws_region).put_object(
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=content.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )
        logger.debug("Uploaded document to s3://%s/%s", settings.s3_bucket, s3_key)
        return s3_key
    except Exception as exc:
        logger.warning("Failed to upload document to S3: %s", exc)
        return None


async def _store_document(
    db: AsyncSession,
    repo_url: str,
    path_str: str,
    parsed: ParsedDocument,
    commit_hash: str | None = None,
) -> Document:
    """Upload content to S3, persist Document metadata, flush to obtain its ID."""
    s3_key = _upload_content_to_s3(repo_url, path_str, parsed.raw_markdown)
    document = Document(
        repo=repo_url,
        path=path_str,
        title=parsed.title,
        s3_key=s3_key,
        commit_hash=commit_hash,
    )
    db.add(document)
    await db.flush()
    return document


async def _store_sections_and_chunks(
    db: AsyncSession,
    document: Document,
    parsed: ParsedDocument,
) -> tuple[list[Chunk], list[str]]:
    """Persist all sections and their chunks. Returns parallel lists for embedding."""
    all_chunks: list[Chunk] = []
    all_chunk_texts: list[str] = []

    for parsed_section in parsed.sections:
        section = Section(
            document_id=document.id,
            heading=parsed_section.heading,
            level=parsed_section.level,
            content=parsed_section.content,
            order_index=parsed_section.order_index,
        )
        db.add(section)
        await db.flush()

        section_chunks = _build_chunk_orm_objects(db, section, chunk_section(parsed_section))
        await db.flush()
        _wire_linked_list(section_chunks)

        all_chunks.extend(section_chunks)
        all_chunk_texts.extend(chunk.chunk_text for chunk in section_chunks)

    return all_chunks, all_chunk_texts


def _build_chunk_orm_objects(db: AsyncSession, section: Section, chunk_data_list: list[ChunkData]) -> list[Chunk]:
    """Create Chunk ORM objects (without embeddings) and add them to the session."""
    section_chunks: list[Chunk] = []
    for cd in chunk_data_list:
        chunk = Chunk(
            section_id=section.id,
            chunk_index=cd.chunk_index,
            chunk_text=cd.chunk_text,
            token_count=cd.token_count,
        )
        db.add(chunk)
        section_chunks.append(chunk)
    return section_chunks


async def _embed_and_assign(all_chunks: list[Chunk], all_chunk_texts: list[str], path_str: str) -> None:
    """Batch-embed all chunk texts and assign embeddings to the ORM objects."""
    if not all_chunk_texts:
        return
    logger.debug("Embedding %d chunks for %s", len(all_chunks), path_str)
    embeddings = await embed_texts(all_chunk_texts)
    for chunk, embedding in zip(all_chunks, embeddings):
        chunk.embedding = embedding


def _store_assets(db: AsyncSession, document: Document, parsed: ParsedDocument) -> None:
    """Persist all asset records for the document."""
    for parsed_asset in parsed.assets:
        db.add(Asset(
            document_id=document.id,
            file_path=parsed_asset.file_path,
            alt_text=parsed_asset.alt_text,
            context=parsed_asset.context,
        ))


def _wire_linked_list(chunks: list[Chunk]) -> None:
    """
    Set previous_chunk_id / next_chunk_id to form a doubly-linked list
    within a section.  Chunks must already have IDs (post-flush).
    """
    for i, chunk in enumerate(chunks):
        chunk.previous_chunk_id = chunks[i - 1].id if i > 0 else None
        chunk.next_chunk_id = chunks[i + 1].id if i < len(chunks) - 1 else None
