"""
Lambda: Extract embedded images from a .docx file stored in S3.

Input event:
  {"bucket": "wiki-rag-dev-uploads", "key": "uploads/<job_id>/file.docx"}

Output:
  {
    "images": [
      {"s3_key": "images/<uuid>.png", "content_type": "image/png"}
    ]
  }

The extracted images are uploaded to the same S3 bucket under the "images/" prefix.
The ingestion worker stores them as Asset records linked to the document.
"""

import io
import json
import logging
import os
import uuid

import boto3
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_s3 = boto3.client("s3")

_CONTENT_TYPE_MAP = {
    "png":  "image/png",
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "gif":  "image/gif",
    "bmp":  "image/bmp",
    "tiff": "image/tiff",
    "webp": "image/webp",
}


def lambda_handler(event: dict, context) -> dict:
    bucket = event["bucket"]
    key    = event["key"]

    logger.info("Extracting images from s3://%s/%s", bucket, key)

    # Download .docx from S3
    obj = _s3.get_object(Bucket=bucket, Key=key)
    docx_bytes = obj["Body"].read()

    # Extract images using python-docx
    images = _extract_images(docx_bytes)

    # Upload each image to S3 under images/ prefix
    uploaded = []
    for ext, image_bytes in images:
        image_key = f"images/{uuid.uuid4()}.{ext}"
        content_type = _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")

        _s3.put_object(
            Bucket=bucket,
            Key=image_key,
            Body=image_bytes,
            ContentType=content_type,
        )
        uploaded.append({"s3_key": image_key, "content_type": content_type})
        logger.info("Uploaded image: s3://%s/%s", bucket, image_key)

    logger.info("Extracted %d images from %s", len(uploaded), key)
    return {"images": uploaded}


def _extract_images(docx_bytes: bytes) -> list[tuple[str, bytes]]:
    """Return a list of (extension, bytes) for every image embedded in the docx."""
    doc = Document(io.BytesIO(docx_bytes))
    images = []

    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                image_part = rel.target_part
                ext = image_part.partname.split(".")[-1].lower()
                images.append((ext, image_part.blob))
            except Exception as exc:
                logger.warning("Skipped image part: %s", exc)

    return images
