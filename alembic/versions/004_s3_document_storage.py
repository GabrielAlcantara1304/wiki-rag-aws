"""Move full document content to S3.

Revision ID: 004
Revises: 003
Create Date: 2026-03-20

Changes:
  - Removes raw_markdown and rendered_text columns from documents table.
    Full content is now stored in S3; the s3_key column holds the reference.
  - Adds s3_key column (nullable VARCHAR 1000).

Note: Existing documents will have s3_key = NULL after this migration.
      Re-ingest documents to populate s3_key and rebuild embeddings.
"""

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("s3_key", sa.String(1000), nullable=True,
                  comment="S3 key for full document content"),
    )
    op.drop_column("documents", "raw_markdown")
    op.drop_column("documents", "rendered_text")


def downgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("rendered_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "documents",
        sa.Column("raw_markdown", sa.Text(), nullable=False, server_default=""),
    )
    op.drop_column("documents", "s3_key")
