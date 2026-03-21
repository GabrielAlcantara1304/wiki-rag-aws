"""
POST /upload — ingest files uploaded directly via the browser.

Accepts multipart/form-data with one or more .md, .docx, or .txt files.
Uploads each file to S3 and enqueues an SQS message for the worker to process.
Returns immediately with a job_id (async processing).
"""

import json
import logging
import uuid
from pathlib import Path

import boto3
from fastapi import APIRouter, HTTPException, UploadFile, File, status

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {".md", ".docx", ".txt"}

_sqs = None
_s3 = None


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
    "/upload",
    summary="Upload and ingest documents",
    description=(
        "Upload .md, .docx, or .txt files. Each file is stored in S3 and "
        "enqueued for async processing by the ingestion worker."
    ),
)
async def upload_files(files: list[UploadFile] = File(...)) -> dict:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nenhum arquivo enviado.",
        )

    if not settings.s3_bucket or not settings.sqs_ingestion_queue_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3_BUCKET e SQS_INGESTION_QUEUE_URL devem estar configurados.",
        )

    # Validate extensions
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Tipo não suportado: '{f.filename}'. Use .md, .docx ou .txt.",
            )

    job_id = str(uuid.uuid4())
    queued = 0

    for f in files:
        content = await f.read()
        file_key = f"uploads/{job_id}/{f.filename}"
        try:
            _get_s3().put_object(
                Bucket=settings.s3_bucket,
                Key=file_key,
                Body=content,
            )
            _get_sqs().send_message(
                QueueUrl=settings.sqs_ingestion_queue_url,
                MessageBody=json.dumps({
                    "file_key": file_key,
                    "repo_url": f"upload:{job_id}",
                    "file_name": f.filename,
                    "job_id": job_id,
                }),
            )
            queued += 1
            logger.info("Queued %s for ingestion (job=%s)", f.filename, job_id)
        except Exception as exc:
            logger.error("Failed to queue %s: %s", f.filename, exc)

    if queued == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao enfileirar arquivos para processamento.",
        )

    return {
        "status": "queued",
        "job_id": job_id,
        "queued": queued,
        "total": len(files),
        "message": (
            f"{queued} arquivo(s) enviado(s) para processamento. "
            f"O worker irá gerar os embeddings em breve."
        ),
    }
