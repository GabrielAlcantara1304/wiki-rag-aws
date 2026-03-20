"""
Embedding generation via OpenAI text-embedding-3-* models.

Design:
  - Async client for non-blocking I/O inside FastAPI / ingestion pipeline.
  - Batch API calls (up to 2048 inputs per request) to minimise round-trips.
  - Exponential back-off with tenacity for rate-limit / transient errors.
  - Dimensions validated against settings to catch misconfiguration early.
"""

import asyncio
import logging

import tiktoken
from openai import AsyncOpenAI, RateLimitError, APIError, BadRequestError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from app.config import settings

logger = logging.getLogger(__name__)

# OpenAI recommends batches of ≤2048; we stay well under to keep latency low
_BATCH_SIZE = 512
_ENCODING = tiktoken.get_encoding("cl100k_base")

_client = AsyncOpenAI(api_key=settings.openai_api_key)

# Hard limit for text-embedding-3-small (8192 tokens)
_MAX_EMBED_TOKENS = 8000  # slightly under limit for safety

def _truncate_to_limit(text: str) -> str:
    """Truncate text to fit within the embedding model's token limit."""
    tokens = _ENCODING.encode(text)
    if len(tokens) <= _MAX_EMBED_TOKENS:
        return text
    logger.warning("Truncating chunk from %d to %d tokens for embedding", len(tokens), _MAX_EMBED_TOKENS)
    return _ENCODING.decode(tokens[:_MAX_EMBED_TOKENS])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of strings.

    Handles batching transparently — caller can pass any number of texts.

    Args:
        texts: Non-empty list of strings to embed.

    Returns:
        Parallel list of embedding vectors (same order as input).
    """
    if not texts:
        return []

    results: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]

    # Split into batches and run them concurrently
    batch_coros = []
    batch_slices = []
    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start : start + _BATCH_SIZE]
        batch_slices.append((start, start + len(batch)))
        batch_coros.append(_embed_batch(batch))

    batch_results = await asyncio.gather(*batch_coros)

    for (start, end), embeddings in zip(batch_slices, batch_results):
        results[start:end] = embeddings

    logger.debug("Embedded %d texts in %d batches", len(texts), len(batch_coros))
    return results


async def embed_query(text: str) -> list[float]:
    """Convenience wrapper for embedding a single query string."""
    vectors = await embed_texts([text])
    return vectors[0]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@retry(
    retry=retry_if_exception_type((RateLimitError,)),  # BadRequestError não deve ser retryed
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(6),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Single API call for one batch.  Decorated with retry for resilience.
    Texts are truncated to _MAX_EMBED_TOKENS before sending.
    """
    texts = [_truncate_to_limit(t) for t in texts]
    response = await _client.embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
        dimensions=settings.openai_embedding_dimensions,
    )
    # The API returns results in the same order as input
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
