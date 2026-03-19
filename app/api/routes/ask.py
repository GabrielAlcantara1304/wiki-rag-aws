"""
POST /ask — answer a question from the wiki knowledge base.

Pipeline:
  1. Validate and clean the question.
  2. Retrieve top-k relevant chunks (vector search + context expansion).
  3. Generate a grounded answer (OpenAI Responses API).
  4. Return answer + structured sources.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AskRequest, AskResponse, SourceItem
from app.database import get_db
from app.generation.generator import generate_answer
from app.models.db_models import KnowledgeGap
from app.retrieval.retriever import search

GAP_SIMILARITY_THRESHOLD = 0.45
GAP_PHRASES = ["não foi encontrada na documentação", "não encontrei", "não há informação"]

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question answered from the wiki",
    description=(
        "Performs vector similarity search over ingested wiki content, "
        "expands context with neighbouring chunks, then uses the OpenAI "
        "Responses API to generate a cited answer."
    ),
)
async def ask(
    body: AskRequest,
    db: AsyncSession = Depends(get_db),
) -> AskResponse:
    logger.info("Question: %s", body.question[:100])

    # Step 1 — Build retrieval query (contextualize short follow-up questions)
    retrieval_query = body.question
    if body.conversation_history:
        last_user = next(
            (m.content for m in reversed(body.conversation_history) if m.role == "user"),
            None,
        )
        if last_user and len(body.question.strip()) < 80:
            retrieval_query = f"{last_user} — {body.question}"
            logger.info("Contextualized retrieval query: %s", retrieval_query[:120])

    # Step 2 — Retrieve relevant chunks
    try:
        chunks = await search(
            db=db,
            question=retrieval_query,
            k=body.top_k,
            repo_filter=body.repo_filter,
        )
    except Exception as exc:
        logger.error("Retrieval failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Retrieval failed: {exc}",
        )

    # Step 3 — Generate answer
    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]
    try:
        answer_text, raw_sources = await generate_answer(
            question=body.question,
            chunks=chunks,
            conversation_history=history,
        )
    except Exception as exc:
        logger.error("Generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Answer generation failed: {exc}",
        )

    # Step 3 — Shape response
    sources = [
        SourceItem(
            document=s["document"],
            section=s["section"],
            snippet=s["snippet"],
            similarity=s["similarity"],
            path=s["path"],
        )
        for s in raw_sources
    ]

    max_sim = max((s["similarity"] for s in raw_sources), default=0.0)

    # Step 4 — Auto-detect knowledge gap
    gap_id = None
    low_confidence = max_sim < GAP_SIMILARITY_THRESHOLD
    no_info = any(phrase in answer_text.lower() for phrase in GAP_PHRASES)
    if low_confidence or no_info:
        try:
            gap = KnowledgeGap(
                id=uuid.uuid4(),
                question=body.question,
                answer_given=answer_text[:1000],
                max_similarity=max_sim,
                source="auto",
                status="open",
            )
            db.add(gap)
            await db.commit()
            gap_id = str(gap.id)
            logger.info("Knowledge gap registered (sim=%.2f): %s", max_sim, body.question[:80])
        except Exception as exc:
            logger.warning("Failed to register knowledge gap: %s", exc)

    return AskResponse(
        answer=answer_text,
        sources=sources,
        total_chunks_retrieved=len(chunks),
        max_similarity=max_sim,
        gap_id=gap_id,
    )
