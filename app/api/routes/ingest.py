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


# ---------------------------------------------------------------------------
# Async folder ingestion via SQS
# ---------------------------------------------------------------------------

import json
import os
import uuid as _uuid

import boto3
from fastapi import UploadFile, File

from app.config import settings

_sqs = None
_s3  = None


def _get_sqs():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=settings.aws_region)
    return _sqs


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=settings.aws_region)
    return _s3


@router.post(
    "/ingest/folder",
    summary="Async folder ingestion via SQS",
    description=(
        "Upload one or more files. Each file is saved to S3 and enqueued in SQS "
        "for async processing by the ingestion worker. Returns immediately with a job_id."
    ),
)
async def ingest_folder(
    files: list[UploadFile] = File(...),
    repo_url: str = "uploaded",
) -> dict:
    if not settings.sqs_ingestion_queue_url or not settings.s3_bucket:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SQS_INGESTION_QUEUE_URL and S3_BUCKET must be configured.",
        )

    job_id = str(_uuid.uuid4())
    queued = 0

    for upload in files:
        file_key = f"uploads/{job_id}/{upload.filename}"
        content = await upload.read()

        try:
            _get_s3().put_object(Bucket=settings.s3_bucket, Key=file_key, Body=content)
            _get_sqs().send_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                MessageBody=json.dumps({
                    "file_key": file_key,
                    "repo_url": repo_url,
                    "file_name": upload.filename,
                    "job_id": job_id,
                }),
            )
            queued += 1
            logger.info("Queued %s (job=%s)", upload.filename, job_id)
        except Exception as exc:
            logger.error("Failed to queue %s: %s", upload.filename, exc)

    return {"job_id": job_id, "queued": queued, "total": len(files)}
