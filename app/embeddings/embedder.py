"""
Embedding generation via Amazon Bedrock — Titan Text Embeddings v2.

Design:
  - boto3 is synchronous; calls are wrapped in asyncio.to_thread for non-blocking I/O.
  - Titan v2 max input: 8192 tokens. Texts are truncated by character count as a
    lightweight guard (no tiktoken dependency on this version).
  - One request per text (Titan v2 does not support batch input in a single call).
  - Exponential back-off with tenacity for throttling errors.
  - IRSA (IAM Roles for Service Accounts) on EKS provides credentials automatically —
    no explicit AWS keys needed in production.

Pricing: $0.00002 per 1K tokens (us-east-1, 2024).
"""

import asyncio
import json
import logging

import boto3
from botocore.exceptions import ClientError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from app.config import settings

logger = logging.getLogger(__name__)

# Titan v2 token limit — use char-based guard (~4 chars/token)
_MAX_CHARS = 8192 * 4

# Lazy-initialised boto3 client (thread-safe, reused across calls)
_bedrock_client = None


def _get_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
        )
    return _bedrock_client


def _truncate(text: str) -> str:
    if len(text) > _MAX_CHARS:
        logger.warning("Truncating text from %d to %d chars for embedding", len(text), _MAX_CHARS)
        return text[:_MAX_CHARS]
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of strings via Bedrock Titan v2.

    Titan does not support batch input — texts are embedded one-by-one
    using asyncio.gather for concurrency.

    Args:
        texts: Non-empty list of strings to embed.

    Returns:
        Parallel list of embedding vectors (same order as input).
    """
    if not texts:
        return []

    coros = [_embed_one(t) for t in texts]
    results = await asyncio.gather(*coros)
    logger.debug("Embedded %d texts via Bedrock Titan v2", len(texts))
    return list(results)


async def embed_query(text: str) -> list[float]:
    """Convenience wrapper for embedding a single query string."""
    return await _embed_one(text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _embed_one(text: str) -> list[float]:
    """Embed a single text via Bedrock Titan Text Embeddings v2."""
    text = _truncate(text)
    body = json.dumps({
        "inputText": text,
        "dimensions": settings.bedrock_embed_dimensions,
        "normalize": True,
    })
    response = await asyncio.to_thread(
        _get_client().invoke_model,
        modelId=settings.bedrock_embed_model,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(response["body"].read())
    return result["embedding"]
