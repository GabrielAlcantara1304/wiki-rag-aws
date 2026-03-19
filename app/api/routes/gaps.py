"""
GET  /gaps          — lista lacunas abertas
POST /gaps/feedback — registra feedback manual (thumbs down)
POST /gaps/{id}/resolve — marca lacuna como resolvida
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import FeedbackRequest, GapItem, GapsResponse
from app.database import get_db
from app.models.db_models import KnowledgeGap

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/gaps", response_model=GapsResponse, summary="Listar lacunas de conhecimento")
async def list_gaps(
    status_filter: str = "open",
    db: AsyncSession = Depends(get_db),
) -> GapsResponse:
    result = await db.execute(
        select(KnowledgeGap)
        .where(KnowledgeGap.status == status_filter)
        .order_by(KnowledgeGap.detected_at.desc())
    )
    gaps = result.scalars().all()
    return GapsResponse(
        gaps=[_to_item(g) for g in gaps],
        total=len(gaps),
    )


@router.post("/gaps/feedback", summary="Registrar feedback negativo do usuário")
async def submit_feedback(
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    gap = KnowledgeGap(
        id=uuid.uuid4(),
        question=body.question,
        answer_given=body.answer_given,
        max_similarity=body.max_similarity,
        source="manual",
        status="open",
    )
    db.add(gap)
    await db.commit()
    logger.info("Manual gap registered for: %s", body.question[:80])
    return {"id": str(gap.id), "status": "registered"}


@router.post("/gaps/{gap_id}/resolve", summary="Marcar lacuna como resolvida")
async def resolve_gap(
    gap_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(KnowledgeGap).where(KnowledgeGap.id == uuid.UUID(gap_id))
    )
    gap = result.scalar_one_or_none()
    if not gap:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lacuna não encontrada.")
    gap.status = "resolved"
    gap.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": gap_id, "status": "resolved"}


def _to_item(g: KnowledgeGap) -> GapItem:
    return GapItem(
        id=str(g.id),
        question=g.question,
        answer_given=g.answer_given,
        max_similarity=g.max_similarity,
        source=g.source,
        status=g.status,
        detected_at=g.detected_at.isoformat() if g.detected_at else "",
    )
