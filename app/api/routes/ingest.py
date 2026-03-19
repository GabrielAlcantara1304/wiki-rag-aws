"""
POST /ingest — trigger wiki ingestion.

The endpoint is intentionally synchronous-looking to the caller:
it runs the full pipeline inline and returns when done.

For very large wikis consider wrapping this in a background task
(FastAPI BackgroundTasks) and returning a job ID instead.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.api.schemas import IngestRequest, IngestResponse
from app.database import AsyncSessionLocal
from app.ingestion.pipeline import run_ingestion

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Ingest a GitHub Wiki repository",
    description=(
        "Clones (or pulls) the specified wiki repo, parses all Markdown files, "
        "generates embeddings, and stores everything in PostgreSQL. "
        "Subsequent calls only re-process changed files unless force_all=true."
    ),
)
async def ingest(body: IngestRequest) -> IngestResponse:
    logger.info("Ingest request received for: %s", body.local_path or body.repo_url)

    if not body.repo_url and not body.local_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe repo_url (URL git) ou local_path (pasta local).",
        )

    # A ingestão gerencia sua própria sessão — é longa demais para o get_db
    async with AsyncSessionLocal() as db:
        try:
            stats = await run_ingestion(
                db=db,
                repo_url=body.repo_url,
                force_all=body.force_all,
                local_path_override=body.local_path,
            )
            # pipeline já commita por arquivo
        except Exception as exc:
            await db.rollback()
            import traceback
            logger.error("Ingestion failed:\n%s", traceback.format_exc())
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ingestion failed: {exc}",
            )

    return IngestResponse(
        status="success" if stats["failed"] == 0 else "partial",
        repo_url=body.local_path or body.repo_url,
        total_files=stats["total"],
        processed=stats["processed"],
        skipped=stats["skipped"],
        failed=stats["failed"],
        message=(
            f"Ingested {stats['processed']} file(s). "
            f"Skipped {stats['skipped']} unchanged. "
            f"Failed: {stats['failed']}."
        ),
    )
