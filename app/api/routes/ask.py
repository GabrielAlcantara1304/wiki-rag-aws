"""
POST /ask — answer a question from the wiki knowledge base.

Pipeline:
  1. Validate and clean the question.
  2. Retrieve top-k relevant chunks (vector search + context expansion).
  3. Generate a grounded answer (Bedrock Claude 3 Haiku).
  4. Return answer + structured sources + relevant images.
"""

import logging
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AskRequest, AskResponse, ImageItem, SourceItem, StatsResponse
from app.config import settings
from app.database import get_db
from app.generation.generator import generate_answer
from app.models.db_models import Asset, Chunk, Document, KnowledgeGap
from app.retrieval.retriever import search

GAP_PHRASES = ["não foi encontrada na documentação", "não encontrei", "não há informação"]

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/assets/{asset_id}", summary="Serve a stored asset file")
async def serve_asset(asset_id: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    try:
        asset_uuid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    asset = await db.get(Asset, asset_uuid)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if asset.file_path.startswith("http://") or asset.file_path.startswith("https://"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset is an external URL")

    document = await db.get(Document, asset.document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    repo_root = Path(document.repo)
    doc_dir = (repo_root / Path(document.path).parent).resolve()
    asset_path = (doc_dir / asset.file_path).resolve()

    try:
        asset_path.relative_to(repo_root.resolve())
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if not asset_path.exists() or not asset_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found")

    media_type, _ = mimetypes.guess_type(str(asset_path))
    return FileResponse(path=str(asset_path), media_type=media_type or "application/octet-stream")


@router.get("/stats", response_model=StatsResponse, summary="Knowledge base statistics")
async def stats(db: AsyncSession = Depends(get_db)) -> StatsResponse:
    doc_count = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    chunk_count = (await db.execute(select(func.count()).select_from(Chunk))).scalar_one()
    return StatsResponse(documents=doc_count, chunks=chunk_count)


def _contextualize_query(question: str, conversation_history: list) -> str:
    """Expand short follow-up questions with the previous user turn for better retrieval."""
    if not conversation_history:
        return question
    last_user = next(
        (m.content for m in reversed(conversation_history) if m.role == "user"),
        None,
    )
    if last_user and len(question.strip()) < 80:
        contextualized = f"{last_user} — {question}"
        logger.info("Contextualized retrieval query: %s", contextualized[:120])
        return contextualized
    return question


async def _register_knowledge_gap(
    db: AsyncSession,
    question: str,
    answer_text: str,
    max_similarity: float,
) -> str | None:
    """Persist a knowledge gap if the answer has low confidence. Returns gap id or None."""
    low_confidence = max_similarity < settings.gap_similarity_threshold
    no_info = any(phrase in answer_text.lower() for phrase in GAP_PHRASES)
    if not (low_confidence or no_info):
        return None
    try:
        gap = KnowledgeGap(
            id=uuid.uuid4(),
            question=question,
            answer_given=answer_text[:1000],
            max_similarity=max_similarity,
            source="auto",
            status="open",
        )
        db.add(gap)
        await db.commit()
        logger.info("Knowledge gap registered (sim=%.2f): %s", max_similarity, question[:80])
        return str(gap.id)
    except Exception as exc:
        logger.warning("Failed to register knowledge gap: %s", exc)
        return None


async def _find_relevant_images(
    db: AsyncSession,
    question: str,
    chunks: list,
) -> list[ImageItem]:
    """Return scored images from documents relevant to the question."""
    try:
        doc_ids = list({chunk.document_id for chunk in chunks})
        if not doc_ids:
            return []

        asset_rows = (await db.execute(
            select(Asset).where(Asset.document_id.in_(doc_ids))
        )).scalars().all()

        query_words = {w for w in question.lower().split() if len(w) >= 3}

        scored: list[tuple[int, Asset, bool]] = []
        for asset in asset_rows:
            is_external = asset.file_path.startswith(("http://", "https://"))
            filename_hint = Path(asset.file_path).stem.replace("-", " ").replace("_", " ")
            haystack = " ".join(filter(None, [
                asset.alt_text if asset.alt_text and asset.alt_text.lower() != "image" else "",
                asset.context or "",
                filename_hint,
            ])).lower()
            score = sum(1 for w in query_words if w in haystack)
            if score > 0:
                scored.append((score, asset, is_external))

        scored.sort(key=lambda x: x[0], reverse=True)
        seen_paths: set[str] = set()
        images: list[ImageItem] = []
        for _, asset, is_external in scored:
            if len(images) >= settings.max_images_per_response:
                break
            if asset.file_path in seen_paths:
                continue
            seen_paths.add(asset.file_path)
            images.append(ImageItem(
                url=asset.file_path if is_external else f"/assets/{asset.id}",
                alt_text=asset.alt_text or "",
            ))
        return images
    except Exception as exc:
        logger.warning("Failed to retrieve images: %s", exc)
        return []


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question answered from the wiki",
    description=(
        "Performs vector similarity search over ingested wiki content, "
        "expands context with neighbouring chunks, then uses Bedrock Claude 3 Haiku "
        "to generate a cited answer."
    ),
)
async def ask(
    body: AskRequest,
    db: AsyncSession = Depends(get_db),
) -> AskResponse:
    logger.info("Question: %s", body.question[:100])

    retrieval_query = _contextualize_query(body.question, body.conversation_history)

    try:
        chunks = await search(db=db, question=retrieval_query, k=body.top_k, repo_filter=body.repo_filter)
    except Exception as exc:
        logger.error("Retrieval failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Retrieval failed: {exc}")

    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]
    try:
        answer_text, raw_sources = await generate_answer(
            question=body.question, chunks=chunks, conversation_history=history,
        )
    except Exception as exc:
        logger.error("Generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Answer generation failed: {exc}")

    sources = [
        SourceItem(document=s["document"], section=s["section"], snippet=s["snippet"],
                   similarity=s["similarity"], path=s["path"])
        for s in raw_sources
    ]
    max_sim = max((s["similarity"] for s in raw_sources), default=0.0)

    gap_id = await _register_knowledge_gap(db, body.question, answer_text, max_sim)
    images = await _find_relevant_images(db, body.question, chunks)

    return AskResponse(
        answer=answer_text,
        sources=sources,
        total_chunks_retrieved=len(chunks),
        max_similarity=max_sim,
        gap_id=gap_id,
        images=images,
    )
