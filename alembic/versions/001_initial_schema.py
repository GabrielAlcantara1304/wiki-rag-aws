"""Initial schema: documents, sections, chunks, assets + pgvector index

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

Notes:
  - pgvector extension is enabled before table creation.
  - HNSW index on chunks.embedding for sub-linear approximate nearest-neighbour
    search.  HNSW is preferred over IVFFlat for small-to-medium datasets because
    it doesn't require a training step and has better recall.
  - Vector dimension (1536) matches text-embedding-3-small.
    Change to 3072 for text-embedding-3-large.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VECTOR_DIMS = 1024  # Titan Text v2 default — must match settings.bedrock_embed_dimensions


def upgrade() -> None:
    # Enable pgvector extension — idempotent
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # documents
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("repo", sa.String(500), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("raw_markdown", sa.Text, nullable=False),
        sa.Column("rendered_text", sa.Text, nullable=False),
        sa.Column("last_modified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commit_hash", sa.String(40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_documents_repo", "documents", ["repo"])
    op.create_unique_constraint(
        "uq_document_repo_path", "documents", ["repo", "path"]
    )

    # ------------------------------------------------------------------
    # sections
    # ------------------------------------------------------------------
    op.create_table(
        "sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("heading", sa.String(500), nullable=True),
        sa.Column("level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_sections_document_id", "sections", ["document_id"])

    # ------------------------------------------------------------------
    # chunks
    # ------------------------------------------------------------------
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedding", Vector(VECTOR_DIMS), nullable=True),
        sa.Column(
            "previous_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "next_chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_chunks_section_id", "chunks", ["section_id"])

    # HNSW index for approximate nearest-neighbour cosine search.
    # m=16 ef_construction=64 are pgvector defaults — good for up to ~1M vectors.
    # Increase m for better recall at the cost of index build time.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ------------------------------------------------------------------
    # assets
    # ------------------------------------------------------------------
    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("alt_text", sa.Text, nullable=True),
        sa.Column("context", sa.Text, nullable=True),
    )
    op.create_index("ix_assets_document_id", "assets", ["document_id"])


def downgrade() -> None:
    op.drop_table("assets")
    op.drop_table("chunks")
    op.drop_table("sections")
    op.drop_table("documents")
    # Leave the extension installed — other schemas may use it
