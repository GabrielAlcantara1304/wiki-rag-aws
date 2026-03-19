"""
ORM models — one class per database table.

Relationships:
  Document  ──< Section  ──< Chunk
  Document  ──< Asset

Cascade deletes are enabled so removing a Document removes all its
child records automatically.  This keeps re-ingestion simple: delete
the document, then re-insert everything.

Vector column: pgvector Vector(n) type.  Dimensions must match
settings.openai_embedding_dimensions (default 1536 for
text-embedding-3-small).
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Document(Base):
    """
    Stores the FULL raw markdown and rendered plain text of every wiki page.
    This is the source of truth — chunks are derived from it, not a replacement.
    """

    __tablename__ = "documents"
    __table_args__ = (
        # Prevent duplicate ingestion of the same file from the same repo
        UniqueConstraint("repo", "path", name="uq_document_repo_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    repo: Mapped[str] = mapped_column(
        String(500), nullable=False, index=True,
        comment="Remote URL or local identifier of the wiki repo",
    )
    path: Mapped[str] = mapped_column(
        String(1000), nullable=False,
        comment="Relative path of the file within the repo (e.g. Home.md)",
    )
    title: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="Inferred from first H1 heading or filename",
    )
    raw_markdown: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Verbatim .md file content — never modified after ingestion",
    )
    rendered_text: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Plain text extracted from markdown (used for display)",
    )
    last_modified: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    commit_hash: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
        comment="Git commit SHA at time of ingestion — drives incremental updates",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    sections: Mapped[list["Section"]] = relationship(
        "Section",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Section.order_index",
    )
    assets: Mapped[list["Asset"]] = relationship(
        "Asset",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class Section(Base):
    """
    A logical block of content bounded by a Markdown heading.
    level=0 means content that appears before the first heading.
    """

    __tablename__ = "sections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    heading: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="The heading text that opens this section (None for root content)",
    )
    level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Heading depth: 0=root, 1=H1, 2=H2, 3=H3",
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="All text content belonging to this section (not including heading line)",
    )
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Position of this section within the document",
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="sections")
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk",
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )


class Chunk(Base):
    """
    A retrieval-optimised slice of a Section with a vector embedding.

    previous_chunk_id / next_chunk_id form a doubly-linked list within
    a section, allowing the retriever to expand context by walking
    neighbours without extra JOIN queries.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="0-based position within the parent section",
    )
    chunk_text: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Text sent to the embedding model and returned as a source snippet",
    )
    token_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Vector type — dimensions configured in alembic migration to match
    # settings.openai_embedding_dimensions
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True  # Titan Text v2 default dims
    )
    previous_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    next_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    section: Mapped["Section"] = relationship("Section", back_populates="chunks")


class Asset(Base):
    """
    Tracks images and other media referenced within a document.
    Preserves alt text and surrounding paragraph for future multimodal retrieval.
    """

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(
        String(1000), nullable=False,
        comment="Path or URL as it appears in the markdown source",
    )
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Surrounding paragraph — useful for future image search",
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="assets")


class KnowledgeGap(Base):
    """
    Registra perguntas para as quais a IA não encontrou boa resposta.
    Alimenta o painel de lacunas visível para quem pode enriquecer a base.
    """

    __tablename__ = "knowledge_gaps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_given: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="auto",
        comment="'auto' = baixa similaridade; 'manual' = feedback do usuário",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", index=True,
        comment="'open' ou 'resolved'",
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
