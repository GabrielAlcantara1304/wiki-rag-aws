"""
SQS Ingestion Worker — consumes async ingestion jobs from SQS.

Each SQS message represents one file to ingest:
  {
    "file_key":   "uploads/My_Document.docx",   # S3 key
    "repo_url":   "my-repo-identifier",
    "file_name":  "My_Document.docx"
  }

The worker:
  1. Downloads the file from S3 to a temp directory.
  2. For .docx: invokes the Lambda image extractor before ingesting.
  3. Calls the standard ingestion pipeline.
  4. Deletes the SQS message on success.
  5. On failure: leaves the message for SQS to retry → DLQ after max retries.

Run as:
  python -m app.ingestion.worker

Kubernetes: separate Deployment using the same image with this command.
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

import boto3

from app.database import AsyncSessionLocal
from app.ingestion.pipeline import _ingest_file
from app.utils.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

_POLL_WAIT_SECONDS = 20   # SQS long-polling window (max 20s)
_MAX_MESSAGES = 10        # messages per poll (max 10)

_sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_s3  = boto3.client("s3",  region_name=os.environ.get("AWS_REGION", "us-east-1"))
_lambda = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-east-1"))

_QUEUE_URL     = os.environ["SQS_INGESTION_QUEUE_URL"]
_S3_BUCKET     = os.environ["S3_BUCKET"]
_LAMBDA_NAME   = os.environ.get("LAMBDA_DOCX_EXTRACTOR_NAME", "")


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------

async def _process_message(body: dict, tmpdir: Path) -> None:
    file_key    = body["file_key"]
    repo_url    = body["repo_url"]
    file_name   = body.get("file_name", Path(file_key).name)
    # rel_path preserves directory structure within the repo (e.g. "docs/Home.md").
    # Falls back to file_name for uploads that have no subdirectory.
    rel_path    = body.get("rel_path", file_name)
    commit_hash = body.get("commit_hash") or None

    # Download preserving relative directory structure so _ingest_file sees the
    # same path hierarchy that the pipeline would expect from a git checkout.
    local_file = tmpdir / rel_path
    local_file.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading s3://%s/%s → %s", _S3_BUCKET, file_key, local_file)
    _s3.download_file(_S3_BUCKET, file_key, str(local_file))

    # For .docx files, extract embedded images via Lambda before ingesting
    if local_file.suffix.lower() == ".docx" and _LAMBDA_NAME:
        _extract_docx_images(file_key, tmpdir)

    async with AsyncSessionLocal() as db:
        await _ingest_file(db, repo_url, tmpdir, Path(rel_path), commit_hash=commit_hash)
        await db.commit()

    logger.info("Ingested: %s", rel_path)


def _extract_docx_images(file_key: str, tmpdir: Path) -> None:
    """Invoke Lambda synchronously to extract images from a .docx file."""
    payload = json.dumps({"bucket": _S3_BUCKET, "key": file_key})
    try:
        response = _lambda.invoke(
            FunctionName=_LAMBDA_NAME,
            InvocationType="RequestResponse",
            Payload=payload.encode(),
        )
        result = json.loads(response["Payload"].read())
        images = result.get("images", [])
        logger.info("Lambda extracted %d images from %s", len(images), file_key)
    except Exception as exc:
        logger.warning("Lambda image extraction failed for %s: %s", file_key, exc)


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------

async def run_worker() -> None:
    logger.info("SQS worker started — polling: %s", _QUEUE_URL)

    while True:
        response = _sqs.receive_message(
            QueueUrl=_QUEUE_URL,
            MaxNumberOfMessages=_MAX_MESSAGES,
            WaitTimeSeconds=_POLL_WAIT_SECONDS,
            MessageAttributeNames=["All"],
        )
        messages = response.get("Messages", [])

        for message in messages:
            receipt_handle = message["ReceiptHandle"]
            try:
                body = json.loads(message["Body"])
                with tempfile.TemporaryDirectory() as tmpdir:
                    await _process_message(body, Path(tmpdir))
                _sqs.delete_message(QueueUrl=_QUEUE_URL, ReceiptHandle=receipt_handle)
            except Exception as exc:
                logger.error(
                    "Failed to process message %s: %s",
                    message.get("MessageId"), exc,
                    exc_info=True,
                )
                # Do NOT delete — SQS retries, then routes to DLQ


if __name__ == "__main__":
    asyncio.run(run_worker())
