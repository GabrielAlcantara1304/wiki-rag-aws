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

import logging
import uuid
from pathlib import Path

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
) -> None:
    """
    Ingest (or re-ingest) a single markdown file.
    Deletes any existing record first to ensure clean state.
    """
    path_str = str(rel_path)
    abs_path = local_path / rel_path

    # Delete stale data (cascades to sections, chunks, assets)
    await delete_document_by_path(db, repo_url, path_str)

    # Parse — route by extension
    suffix = abs_path.suffix.lower()
    if suffix == ".docx":
        file_bytes = abs_path.read_bytes()
        parsed: ParsedDocument = parse_docx_file(path_str, file_bytes)
    else:  # .md and .txt both go through the markdown parser
        raw_markdown = abs_path.read_text(encoding="utf-8", errors="replace")
        parsed: ParsedDocument = parse_markdown_file(path_str, raw_markdown)

    # Get per-file commit hash for future change detection
    commit_hash = get_file_commit_hash(local_path, rel_path)

    # Persist document (full content preserved)
    document = Document(
        repo=repo_url,
        path=path_str,
        title=parsed.title,
        raw_markdown=parsed.raw_markdown,
        rendered_text=parsed.rendered_text,
        commit_hash=commit_hash,
    )
    db.add(document)
    # We need the document ID immediately for FK relationships
    await db.flush()

    # Persist sections and collect chunks for batch embedding
    all_chunks: list[Chunk] = []   # ORM objects (embedding=None initially)
    all_chunk_texts: list[str] = []  # parallel list for embed_texts()

    for parsed_section in parsed.sections:
        section = Section(
            document_id=document.id,
            heading=parsed_section.heading,
            level=parsed_section.level,
            content=parsed_section.content,
            order_index=parsed_section.order_index,
        )
        db.add(section)
        await db.flush()  # need section.id for chunk FKs

        # Chunk the section
        chunk_data_list: list[ChunkData] = chunk_section(parsed_section)

        # Create ORM objects without embeddings yet
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
            all_chunks.append(chunk)
            all_chunk_texts.append(cd.chunk_text)

        # Flush to get chunk IDs, then wire linked list
        await db.flush()
        _wire_linked_list(section_chunks)

    # Batch embed ALL chunks for this file in one call (or batched internally)
    logger.debug("Embedding %d chunks for %s", len(all_chunks), path_str)
    if all_chunk_texts:
        embeddings = await embed_texts(all_chunk_texts)
        for chunk, embedding in zip(all_chunks, embeddings):
            chunk.embedding = embedding

    # Persist assets
    for parsed_asset in parsed.assets:
        asset = Asset(
            document_id=document.id,
            file_path=parsed_asset.file_path,
            alt_text=parsed_asset.alt_text,
            context=parsed_asset.context,
        )
        db.add(asset)


def _wire_linked_list(chunks: list[Chunk]) -> None:
    """
    Set previous_chunk_id / next_chunk_id to form a doubly-linked list
    within a section.  Chunks must already have IDs (post-flush).
    """
    for i, chunk in enumerate(chunks):
        chunk.previous_chunk_id = chunks[i - 1].id if i > 0 else None
        chunk.next_chunk_id = chunks[i + 1].id if i < len(chunks) - 1 else None
