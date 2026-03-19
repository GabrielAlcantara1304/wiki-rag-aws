"""
POST /upload — ingest files uploaded directly via the browser.

Accepts multipart/form-data with one or more .md or .docx files.
Saves them to a temporary directory and runs the ingestion pipeline.
"""

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, status

from app.api.schemas import IngestResponse
from app.database import AsyncSessionLocal
from app.ingestion.pipeline import run_ingestion

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {".md", ".docx", ".txt"}


@router.post(
    "/upload",
    response_model=IngestResponse,
    summary="Upload and ingest documents",
    description="Upload .md or .docx files for ingestion into the knowledge base.",
)
async def upload_files(files: list[UploadFile] = File(...)) -> IngestResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nenhum arquivo enviado.",
        )

    # Validate extensions
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Tipo não suportado: '{f.filename}'. Use .md ou .docx.",
            )

    # Save to a temp directory
    tmp_dir = tempfile.mkdtemp(prefix="wiki_rag_upload_")
    try:
        for f in files:
            dest = Path(tmp_dir) / f.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            logger.info("Saved upload: %s (%d bytes)", f.filename, dest.stat().st_size)

        async with AsyncSessionLocal() as db:
            try:
                stats = await run_ingestion(
                    db=db,
                    local_path_override=tmp_dir,
                    force_all=True,
                )
            except Exception as exc:
                await db.rollback()
                logger.error("Ingestion of uploaded files failed: %s", exc, exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Falha na ingestão: {exc}",
                )

        return IngestResponse(
            status="success" if stats["failed"] == 0 else "partial",
            repo_url=f"upload:{tmp_dir}",
            total_files=stats["total"],
            processed=stats["processed"],
            skipped=stats["skipped"],
            failed=stats["failed"],
            message=(
                f"{stats['processed']} arquivo(s) processado(s). "
                f"{stats['skipped']} sem alterações. "
                f"{stats['failed']} erro(s)."
            ),
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
