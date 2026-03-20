"""knowledge_gaps table

Revision ID: 002
Revises: 001
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_given", sa.Text(), nullable=True),
        sa.Column("max_similarity", sa.Float(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="auto"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_knowledge_gaps_status", "knowledge_gaps", ["status"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_knowledge_gaps_status", table_name="knowledge_gaps")
    op.drop_table("knowledge_gaps")
