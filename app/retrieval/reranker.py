"""
Cross-encoder reranker using sentence-transformers.

After the vector search returns N candidates, the reranker reads each
(query, chunk_text) pair jointly and produces a relevance score that is
far more accurate than cosine similarity alone.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
  - ~90 MB download on first use (cached in ~/.cache/huggingface)
  - ~20ms per candidate on CPU (fast enough for top-50 candidates)
  - Trained on MS MARCO passage ranking — excellent for Q&A retrieval
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reranker")
_model: CrossEncoder | None = None


def _get_model() -> CrossEncoder:
    """Lazy-load the model on first use."""
    global _model
    if _model is None:
        logger.info("Loading cross-encoder model: %s", _MODEL_NAME)
        _model = CrossEncoder(_MODEL_NAME, max_length=512)
        logger.info("Cross-encoder model loaded.")
    return _model


def _rerank_sync(query: str, texts: list[str], top_k: int) -> list[int]:
    """
    Score each (query, text) pair and return indices sorted by score desc.
    Runs synchronously — call via run_in_executor to avoid blocking the loop.
    """
    model = _get_model()
    pairs = [(query, t) for t in texts]
    scores = model.predict(pairs)
    ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return ranked_indices[:top_k]


async def rerank(query: str, texts: list[str], top_k: int) -> list[int]:
    """
    Async wrapper: runs the CPU-bound cross-encoder in a thread pool.

    Args:
        query:  The user's original question.
        texts:  List of candidate chunk texts (parallel to the chunk list).
        top_k:  How many top indices to return.

    Returns:
        List of indices into `texts`, ordered by reranker score (best first).
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        _rerank_sync,
        query,
        texts,
        top_k,
    )
