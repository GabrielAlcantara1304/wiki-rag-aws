"""
Embedding generation via AWS Bedrock — Titan Text Embeddings V2.

Uses asyncio.run_in_executor to keep the async interface while calling
the synchronous boto3 SDK. Parallelises individual embed calls for
throughput (Titan V2 processes one text per API call).

Dimensions: 1024 (default for Titan V2) — must match the vector column
in the DB schema and settings.bedrock_embed_dimensions.
"""

import asyncio
import json
import logging
from functools import partial

import boto3
import tiktoken
from botocore.exceptions import ClientError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)

_ENCODING = tiktoken.get_encoding("cl100k_base")
_MAX_EMBED_TOKENS = 8000  # Titan V2 limit is 8192 tokens

_client = boto3.client("bedrock-runtime", region_name=settings.aws_region)


def _truncate_to_limit(text: str) -> str:
    tokens = _ENCODING.encode(text)
    if len(tokens) <= _MAX_EMBED_TOKENS:
        return text
    logger.warning("Truncating chunk from %d to %d tokens for embedding", len(tokens), _MAX_EMBED_TOKENS)
    return _ENCODING.decode(tokens[:_MAX_EMBED_TOKENS])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Parallelises calls to Bedrock Titan V2."""
    if not texts:
        return []
    tasks = [_embed_single(text) for text in texts]
    results = await asyncio.gather(*tasks)
    logger.debug("Embedded %d texts via Bedrock Titan V2", len(texts))
    return list(results)


async def embed_query(text: str) -> list[float]:
    """Convenience wrapper for a single query string."""
    vectors = await embed_texts([text])
    return vectors[0]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(4),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _embed_single(text: str) -> list[float]:
    """Embed one text via Bedrock (async via executor)."""
    truncated = _truncate_to_limit(text)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_invoke_titan, truncated))


def _invoke_titan(text: str) -> list[float]:
    body = json.dumps({
        "inputText": text,
        "dimensions": settings.bedrock_embed_dimensions,
        "normalize": True,
    })
    response = _client.invoke_model(
        modelId=settings.bedrock_embed_model,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]
