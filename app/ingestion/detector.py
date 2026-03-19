"""
Change detection for incremental re-indexing.

Compares the commit hash stored in the `documents` table against the
current HEAD commit for each file.  Only changed or new files are
re-ingested, making large wikis much faster to keep up-to-date.

Two strategies are supported:
  - "commit_hash": compare per-file last-commit SHA (most precise).
  - "force_all":   ignore cache and re-ingest everything (used for full reindex).
"""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.cloner import get_file_commit_hash
from app.models.db_models import Document

logger = logging.getLogger(__name__)


async def detect_changed_files(
    db: AsyncSession,
    repo_url: str,
    local_path: Path,
    md_files: list[Path],
    force_all: bool = False,
) -> tuple[list[Path], list[Path]]:
    """
    Determine which files need ingestion.

    Args:
        db:         Async DB session.
        repo_url:   Remote URL (used as the `repo` key in the DB).
        local_path: Local clone root.
        md_files:   List of relative .md paths found in the repo.
        force_all:  If True, return all files as changed.

    Returns:
        Tuple of (new_or_changed_files, unchanged_files).
    """
    if force_all:
        logger.info("force_all=True — scheduling all %d files for re-ingestion", len(md_files))
        return list(md_files), []

    # Load existing commit hashes from the DB keyed by path
    stmt = select(Document.path, Document.commit_hash).where(Document.repo == repo_url)
    rows = (await db.execute(stmt)).all()
    db_hashes: dict[str, str | None] = {row.path: row.commit_hash for row in rows}

    changed: list[Path] = []
    unchanged: list[Path] = []

    for rel_path in md_files:
        path_str = str(rel_path)
        current_hash = get_file_commit_hash(local_path, rel_path)

        stored_hash = db_hashes.get(path_str)

        if stored_hash is None:
            # New file not yet in DB
            logger.debug("NEW: %s", path_str)
            changed.append(rel_path)
        elif stored_hash != current_hash:
            logger.debug("CHANGED: %s  (was %s, now %s)", path_str, stored_hash[:8] if stored_hash else "none", current_hash[:8] if current_hash else "none")
            changed.append(rel_path)
        else:
            unchanged.append(rel_path)

    logger.info(
        "Change detection: %d changed/new, %d unchanged (out of %d total)",
        len(changed), len(unchanged), len(md_files),
    )
    return changed, unchanged


async def delete_document_by_path(
    db: AsyncSession, repo_url: str, path: str
) -> None:
    """
    Delete a document (and all cascade children) before re-ingesting.
    Called when a file is detected as changed.
    """
    stmt = select(Document).where(Document.repo == repo_url, Document.path == path)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()
    if doc:
        await db.delete(doc)
        logger.debug("Deleted stale document: %s", path)
