"""
Central configuration loaded from environment variables / .env file.
All secrets and tunable parameters live here — never hardcoded elsewhere.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # AWS
    # ------------------------------------------------------------------
    aws_region: str = Field(
        default="us-east-1",
        description="AWS region for Bedrock, SQS, S3, Secrets Manager",
    )

    # ------------------------------------------------------------------
    # Bedrock — Embeddings
    # ------------------------------------------------------------------
    bedrock_embed_model: str = Field(
        default="amazon.titan-embed-text-v2:0",
        description="Bedrock model ID for chunk and query embeddings",
    )
    bedrock_embed_dimensions: int = Field(
        default=1024,
        description="Output dimensions for Titan Embeddings V2 (256 | 512 | 1024)",
    )

    # ------------------------------------------------------------------
    # Bedrock — Chat / Generation
    # ------------------------------------------------------------------
    bedrock_chat_model: str = Field(
        default="anthropic.claude-3-5-haiku-20241022-v1:0",
        description="Bedrock model ID for answer generation",
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/wiki_rag"
    )
    database_url_sync: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/wiki_rag"
    )

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    wiki_repo_url: str = Field(default="", description="Git URL of the wiki to ingest")
    wiki_clone_dir: str = Field(default="/tmp/wiki_repos")

    # ------------------------------------------------------------------
    # Async ingestion via SQS
    # ------------------------------------------------------------------
    sqs_ingestion_queue_url: str = Field(
        default="",
        description="SQS queue URL for async folder ingestion jobs",
    )
    s3_bucket: str = Field(
        default="",
        description="S3 bucket for uploaded files and extracted images",
    )
    lambda_docx_extractor_name: str = Field(
        default="",
        description="Lambda function name/ARN for extracting images from .docx",
    )

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    retrieval_top_k: int = Field(default=10)
    retrieval_similarity_threshold: float = Field(default=0.5)
    context_window_chunks: int = Field(default=2)

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------
    max_chunk_tokens: int = Field(default=800)
    chunk_overlap_tokens: int = Field(default=100)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    generation_temperature: float = Field(default=0.1)
    conversation_history_turns: int = Field(default=3)
    gap_similarity_threshold: float = Field(default=0.45)
    max_images_per_response: int = Field(default=3)
    generation_context: str = Field(
        default="",
        description="Optional domain-specific context injected into every prompt",
    )

    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    cors_origins: list[str] = Field(
        default=[],
        description="Allowed CORS origins in production",
    )

    model_config = {"env_file": ".env", "case_sensitive": False}


settings = Settings()
