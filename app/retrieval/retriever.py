"""
Retrieval layer: vector similarity search + cross-encoder reranking + context expansion.

Flow:
  1. Embed the incoming query.
  2. Cosine-distance search — fetch top_k * 5 candidates from pgvector.
  3. Deduplicate by chunk text content.
  4. Filter out low-content chunks (< MIN_CHUNK_TOKENS tokens).
  5. Cross-encoder reranker scores each (query, chunk) pair jointly — far
     more accurate than cosine similarity for relevance ranking.
  6. Keep top_k after reranking.
  7. Expand each matched chunk with neighbouring chunks for context.
"""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.embeddings.embedder import embed_query
from app.models.db_models import Chunk, Document, Section
from app.retrieval.reranker import rerank as cross_encoder_rerank

logger = logging.getLogger(__name__)

# Chunks with fewer tokens than this are likely headings or empty sections —
# skip them so the reranker doesn't waste slots on content-free results.
_MIN_CHUNK_TOKENS = 20

# How many vector-search candidates to retrieve before reranking
_CANDIDATE_MULTIPLIER = 5


@dataclass
class ChunkResult:
    chunk_id: uuid.UUID
    chunk_text: str
    chunk_index: int
    token_count: int
    similarity: float

    section_id: uuid.UUID
    section_heading: str | None
    section_level: int

    document_id: uuid.UUID
    document_title: str
    document_path: str
    document_repo: str

    # Neighbouring chunks appended for context expansion
    context_chunks: list["ChunkResult"] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search(
    db: AsyncSession,
    question: str,
    k: int | None = None,
    similarity_threshold: float | None = None,
    repo_filter: str | None = None,
) -> list[ChunkResult]:
    """
    Full retrieval pipeline for a natural language question.

    Args:
        db:                   Async DB session.
        question:             Raw user question.
        k:                    Number of top chunks to retrieve (defaults to settings).
        similarity_threshold: Minimum cosine similarity (defaults to settings).
        repo_filter:          If provided, restrict search to this repo URL.

    Returns:
        Ordered list of ChunkResult (most relevant first).
    """
    top_k = k or settings.retrieval_top_k
    threshold = similarity_threshold or settings.retrieval_similarity_threshold

    # Step 1 — embed the question
    query_vector = await embed_query(question)

    # Step 2 — vector search: fetch many more candidates than needed
    candidates = await _vector_search(
        db, query_vector, top_k * _CANDIDATE_MULTIPLIER, threshold, repo_filter
    )

    # Step 3 — deduplicate by chunk text + filter low-content chunks
    seen_texts: set[str] = set()
    filtered: list[ChunkResult] = []
    for r in candidates:
        if r.token_count < _MIN_CHUNK_TOKENS:
            continue
        if r.chunk_text not in seen_texts:
            seen_texts.add(r.chunk_text)
            filtered.append(r)

    if not filtered:
        logger.info("No results above threshold %.2f for query: %s", threshold, question[:80])
        return []

    # Step 4 — cross-encoder reranking: score each (query, chunk) pair jointly
    texts = [r.chunk_text for r in filtered]
    top_indices = await cross_encoder_rerank(question, texts, top_k=top_k)
    results = [filtered[i] for i in top_indices]

    # Step 5 — context expansion (neighbouring chunks)
    expanded = await _expand_context(db, results)

    logger.info(
        "Retrieved %d candidates → reranked to %d chunks for query: %s",
        len(filtered), len(results), question[:80],
    )
    return expanded


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _vector_search(
    db: AsyncSession,
    query_vector: list[float],
    k: int,
    threshold: float,
    repo_filter: str | None,
) -> list[ChunkResult]:
    """
    Execute the pgvector cosine-distance query and map rows to ChunkResult.

    pgvector <=> operator returns cosine DISTANCE (0 = identical, 2 = opposite).
    We convert to similarity: sim = 1 - distance.
    """
    # Build query: select chunks + their section + document in one round-trip
    stmt = (
        select(
            Chunk,
            Section,
            Document,
            # Compute cosine distance inline; alias for ordering
            Chunk.embedding.cosine_distance(query_vector).label("distance"),
        )
        .join(Section, Chunk.section_id == Section.id)
        .join(Document, Section.document_id == Document.id)
        .where(Chunk.embedding.is_not(None))
        .order_by("distance")
        .limit(k)
    )

    if repo_filter:
        stmt = stmt.where(Document.repo == repo_filter)

    rows = (await db.execute(stmt)).all()

    results: list[ChunkResult] = []
    for chunk, section, document, distance in rows:
        similarity = 1.0 - float(distance)
        if similarity < threshold:
            continue

        results.append(ChunkResult(
            chunk_id=chunk.id,
            chunk_text=chunk.chunk_text,
            chunk_index=chunk.chunk_index,
            token_count=chunk.token_count,
            similarity=round(similarity, 4),
            section_id=section.id,
            section_heading=section.heading,
            section_level=section.level,
            document_id=document.id,
            document_title=document.title,
            document_path=document.path,
            document_repo=document.repo,
        ))

    return results


async def _expand_context(
    db: AsyncSession,
    results: list[ChunkResult],
) -> list[ChunkResult]:
    """
    For each matched chunk, fetch up to settings.context_window_chunks
    neighbours in each direction and attach them as context_chunks.

    Uses a set to avoid fetching the same chunk twice across different
    matched results.
    """
    window = settings.context_window_chunks
    if window <= 0:
        return results

    # Collect all chunk IDs we already have so we can skip them
    matched_ids = {r.chunk_id for r in results}

    for result in results:
        # Walk the linked list in both directions
        before = await _walk_linked_list(db, result.chunk_id, direction="prev", steps=window)
        after = await _walk_linked_list(db, result.chunk_id, direction="next", steps=window)

        context: list[ChunkResult] = []
        for chunk, section, document in before[::-1]:  # reverse so oldest is first
            if chunk.id not in matched_ids:
                context.append(_to_chunk_result(chunk, section, document, similarity=0.0))
        for chunk, section, document in after:
            if chunk.id not in matched_ids:
                context.append(_to_chunk_result(chunk, section, document, similarity=0.0))

        result.context_chunks = context

    return results


async def _walk_linked_list(
    db: AsyncSession,
    start_id: uuid.UUID,
    direction: str,  # "prev" | "next"
    steps: int,
) -> list[tuple]:
    """
    Follow previous_chunk_id or next_chunk_id up to `steps` hops.
    Returns a list of (Chunk, Section, Document) tuples.
    """
    collected = []
    current_id = start_id

    for _ in range(steps):
        # Get the current chunk to find the neighbour ID
        current_stmt = (
            select(Chunk, Section, Document)
            .join(Section, Chunk.section_id == Section.id)
            .join(Document, Section.document_id == Document.id)
            .where(Chunk.id == current_id)
        )
        row = (await db.execute(current_stmt)).first()
        if row is None:
            break

        chunk, section, document = row
        neighbour_id = chunk.previous_chunk_id if direction == "prev" else chunk.next_chunk_id
        if neighbour_id is None:
            break

        # Fetch the neighbour
        neighbour_stmt = (
            select(Chunk, Section, Document)
            .join(Section, Chunk.section_id == Section.id)
            .join(Document, Section.document_id == Document.id)
            .where(Chunk.id == neighbour_id)
        )
        neighbour_row = (await db.execute(neighbour_stmt)).first()
        if neighbour_row is None:
            break

        collected.append(neighbour_row)
        current_id = neighbour_row[0].id

    return collected


def _to_chunk_result(chunk: Chunk, section: Section, document: Document, similarity: float) -> ChunkResult:
    return ChunkResult(
        chunk_id=chunk.id,
        chunk_text=chunk.chunk_text,
        chunk_index=chunk.chunk_index,
        token_count=chunk.token_count,
        similarity=similarity,
        section_id=section.id,
        section_heading=section.heading,
        section_level=section.level,
        document_id=document.id,
        document_title=document.title,
        document_path=document.path,
        document_repo=document.repo,
    )
