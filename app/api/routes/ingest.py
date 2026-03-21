"""
Ingestion routes — all three endpoints use the same decoupled model:
  1. Clone / resolve local path in the API pod.
  2. Detect which files changed (needs DB for commit-hash comparison).
  3. Upload each file to S3 (staging prefix uploads/).
  4. Enqueue one SQS message per file.
  5. Return immediately — the worker pod does parsing, embedding, and storage.

Endpoints:
  POST /ingest         — git repo (or local server path)
  POST /ingest/folder  — multipart file upload (kept for direct browser upload)
"""

import json
import logging
import os
import uuid as _uuid
from pathlib import Path

import boto3
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.api.schemas import IngestRequest
from app.config import settings
from app.database import AsyncSessionLocal
from app.ingestion.cloner import (
    clone_or_pull,
    get_file_commit_hash,
    list_markdown_files,
)
from app.ingestion.detector import detect_changed_files

logger = logging.getLogger(__name__)
router = APIRouter()

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


def _require_aws() -> None:
    if not settings.s3_bucket or not settings.sqs_ingestion_queue_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3_BUCKET e SQS_INGESTION_QUEUE_URL devem estar configurados.",
        )


# ---------------------------------------------------------------------------
# POST /ingest  — git repo or local server path
# ---------------------------------------------------------------------------

@router.post(
    "/ingest",
    summary="Ingest a git wiki repository (async)",
    description=(
        "Clones (or pulls) the repo, detects changed files, uploads each to S3, "
        "and enqueues an SQS job per file. Returns immediately with a job_id. "
        "The worker pod handles parsing, embedding, and storage."
    ),
)
async def ingest(body: IngestRequest) -> dict:
    if not body.repo_url and not body.local_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Informe repo_url (URL git) ou local_path (pasta local).",
        )

    _require_aws()

    repo_key = body.local_path or body.repo_url
    logger.info("Ingest request for: %s (force_all=%s)", repo_key, body.force_all)

    # Step 1 — resolve local path
    if body.local_path:
        local_path = Path(body.local_path)
        if not local_path.exists():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Pasta não encontrada: {body.local_path}",
            )
    else:
        try:
            local_path, _ = clone_or_pull(body.repo_url)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Falha ao clonar repositório: {exc}",
            )

    # Step 2 — enumerate files
    md_files = list_markdown_files(local_path)
    if not md_files:
        return {
            "status": "ok", "job_id": None, "queued": 0,
            "skipped": 0, "total": 0,
            "message": "Nenhum arquivo .md/.docx/.txt encontrado.",
        }

    # Step 3 — detect changed files (needs DB for commit-hash comparison)
    async with AsyncSessionLocal() as db:
        changed_files, unchanged_files = await detect_changed_files(
            db, repo_key, local_path, md_files, force_all=body.force_all
        )

    if not changed_files:
        return {
            "status": "ok", "job_id": None, "queued": 0,
            "skipped": len(unchanged_files), "total": len(md_files),
            "message": f"Nenhum arquivo alterado. {len(unchanged_files)} ignorado(s).",
        }

    # Step 4 — upload each changed file to S3 + enqueue SQS
    job_id = str(_uuid.uuid4())
    queued = 0

    for rel_path in changed_files:
        abs_path = local_path / rel_path
        rel_str  = str(rel_path).replace(os.sep, "/")
        commit_hash = get_file_commit_hash(local_path, rel_path) or ""

        try:
            file_key = f"uploads/{job_id}/{rel_str}"
            _get_s3().put_object(
                Bucket=settings.s3_bucket,
                Key=file_key,
                Body=abs_path.read_bytes(),
            )
            _get_sqs().send_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                MessageBody=json.dumps({
                    "file_key":    file_key,
                    "repo_url":    repo_key,
                    "file_name":   abs_path.name,
                    "rel_path":    rel_str,
                    "commit_hash": commit_hash,
                    "job_id":      job_id,
                }),
            )
            queued += 1
            logger.info("Queued %s (job=%s)", rel_str, job_id)
        except Exception as exc:
            logger.error("Failed to queue %s: %s", rel_str, exc)

    return {
        "status": "queued",
        "job_id": job_id,
        "queued": queued,
        "skipped": len(unchanged_files),
        "total": len(md_files),
        "message": (
            f"{queued} arquivo(s) enfileirado(s) para processamento. "
            f"{len(unchanged_files)} ignorado(s) (sem alterações)."
        ),
    }


# ---------------------------------------------------------------------------
# POST /ingest/folder  — multipart file upload (browser direct)
# ---------------------------------------------------------------------------

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
    _require_aws()

    job_id = str(_uuid.uuid4())
    queued = 0

    for upload in files:
        file_key = f"uploads/{job_id}/{upload.filename}"
        content  = await upload.read()

        try:
            _get_s3().put_object(Bucket=settings.s3_bucket, Key=file_key, Body=content)
            _get_sqs().send_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                MessageBody=json.dumps({
                    "file_key":  file_key,
                    "repo_url":  repo_url,
                    "file_name": upload.filename,
                    "rel_path":  upload.filename,
                    "job_id":    job_id,
                }),
            )
            queued += 1
            logger.info("Queued %s (job=%s)", upload.filename, job_id)
        except Exception as exc:
            logger.error("Failed to queue %s: %s", upload.filename, exc)

    return {"job_id": job_id, "queued": queued, "total": len(files)}
