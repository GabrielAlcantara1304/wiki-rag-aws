"""
Central configuration loaded from environment variables / .env file.
All secrets and tunable parameters live here — never hardcoded elsewhere.

AWS Version:
  - LLM      : Amazon Bedrock — Claude 3 Haiku (cheapest Claude, good PT-BR)
  - Embeddings: Amazon Bedrock — Titan Text v2 (multilingual, cheapest)
  - Database  : Amazon RDS PostgreSQL + pgvector
  - Secrets   : AWS Secrets Manager (prod) / .env (dev)
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # AWS / Bedrock
    # ------------------------------------------------------------------
    aws_region: str = Field(default="us-east-1", description="AWS region for Bedrock")

    # LLM: Claude 3 Haiku — cheapest Claude on Bedrock, strong PT-BR support
    bedrock_llm_model: str = Field(
        default="anthropic.claude-3-haiku-20240307-v1:0",
        description="Bedrock model ID for answer generation",
    )

    # Embeddings: Titan Text v2 — multilingual, $0.00002/1K tokens
    bedrock_embed_model: str = Field(
        default="amazon.titan-embed-text-v2:0",
        description="Bedrock model ID for embeddings",
    )
    bedrock_embed_dimensions: int = Field(
        default=1024,
        description="Titan v2 supports 256 | 512 | 1024 dims",
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    # Async URL (asyncpg) — used by SQLAlchemy at runtime
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/wiki_rag"
    )
    # Sync URL (psycopg2) — used by Alembic for migrations
    database_url_sync: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/wiki_rag"
    )

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    wiki_repo_url: str = Field(
        default="",
        description="Git URL of the wiki repository to ingest",
    )
    wiki_clone_dir: str = Field(
        default="/tmp/wiki_repos",
        description="Host path where repos are cloned",
    )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    retrieval_top_k: int = Field(
        default=10,
        description="Number of top chunks returned by similarity search",
    )
    retrieval_similarity_threshold: float = Field(
        default=0.5,
        description="Cosine similarity floor — results below this are discarded",
    )
    context_window_chunks: int = Field(
        default=2,
        description="How many neighboring chunks to add around each matched chunk",
    )

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------
    max_chunk_tokens: int = Field(
        default=800,
        description="Hard upper limit for a single chunk (tokens)",
    )
    chunk_overlap_tokens: int = Field(
        default=100,
        description="Overlap appended from previous chunk for continuity",
    )

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    generation_temperature: float = Field(
        default=0.1,
        description="LLM temperature — lower means more deterministic/factual answers",
    )
    conversation_history_turns: int = Field(
        default=3,
        description="Number of previous conversation turns injected into the prompt",
    )
    gap_similarity_threshold: float = Field(
        default=0.45,
        description="Max similarity below which a question is flagged as a knowledge gap",
    )
    max_images_per_response: int = Field(
        default=3,
        description="Maximum number of images attached to a single answer",
    )
    generation_context: str = Field(
        default="",
        description="Optional domain-specific background context injected into every prompt",
    )

    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


# Singleton — import this everywhere instead of re-creating
settings = Settings()
