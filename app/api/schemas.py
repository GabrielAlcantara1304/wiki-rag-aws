"""
Pydantic request / response schemas for the FastAPI endpoints.
Kept separate from ORM models to avoid coupling the API contract to DB internals.
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


# ---------------------------------------------------------------------------
# /ingest
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    repo_url: str = Field(
        default="",
        description="Git URL of the wiki repository to ingest",
        examples=["https://github.com/your-org/your-wiki.git"],
    )
    local_path: str = Field(
        default="",
        description="Caminho local para a pasta da wiki já clonada (alternativa ao repo_url)",
        examples=["C:/Users/gabriel/minha-wiki"],
    )
    force_all: bool = Field(
        default=False,
        description=(
            "If true, re-ingest every file even if unchanged. "
            "Use this for a full reindex after schema changes."
        ),
    )


class IngestResponse(BaseModel):
    status: str
    repo_url: str
    total_files: int
    processed: int
    skipped: int
    failed: int
    message: str


# ---------------------------------------------------------------------------
# /ask
# ---------------------------------------------------------------------------

class ConversationMessage(BaseModel):
    role: str = Field(description="'user' or 'assistant'")
    content: str = Field(description="Message content")


class AskRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="Natural language question to answer from the wiki",
        examples=["How do I configure the deployment pipeline?"],
    )
    repo_filter: Optional[str] = Field(
        default=None,
        description=(
            "Restrict retrieval to a specific repo URL. "
            "Leave empty to search across all ingested wikis."
        ),
    )
    top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description="Override number of chunks to retrieve",
    )
    conversation_history: list[ConversationMessage] = Field(
        default=[],
        description="Previous turns of the conversation for multi-turn context",
    )


class SourceItem(BaseModel):
    document: str = Field(description="Title of the source document")
    section: str = Field(description="Section heading where the answer was found")
    snippet: str = Field(description="Relevant excerpt from the source")
    similarity: float = Field(description="Cosine similarity score (0–1)")
    path: str = Field(description="Relative file path in the repository")


class ImageItem(BaseModel):
    url: str
    alt_text: str


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    total_chunks_retrieved: int
    max_similarity: Optional[float] = None
    gap_id: Optional[str] = None
    images: list[ImageItem] = []


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------

class StatsResponse(BaseModel):
    documents: int
    chunks: int


# ---------------------------------------------------------------------------
# /gaps
# ---------------------------------------------------------------------------

class GapItem(BaseModel):
    id: str
    question: str
    answer_given: Optional[str] = None
    max_similarity: Optional[float] = None
    source: str
    status: str
    detected_at: str

class GapsResponse(BaseModel):
    gaps: list[GapItem]
    total: int

class FeedbackRequest(BaseModel):
    question: str
    answer_given: Optional[str] = None
    max_similarity: Optional[float] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"
