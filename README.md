# Wiki RAG — Internal AI Assistant

A production-ready RAG (Retrieval-Augmented Generation) system that answers questions from a GitHub Wiki. Built on FastAPI, PostgreSQL + pgvector, and the OpenAI API.

---

## Architecture

```
GitHub Wiki (git)
       │
       ▼
 ┌─────────────┐
 │  Ingestion  │  clone/pull → parse → chunk → embed → store
 └─────────────┘
       │
       ▼
 ┌─────────────────────────────────────────────────┐
 │  PostgreSQL + pgvector                          │
 │  documents → sections → chunks (embeddings)    │
 │                       → assets                 │
 └─────────────────────────────────────────────────┘
       │
       ▼
 ┌─────────────┐     ┌────────────┐     ┌────────────┐
 │  /ask API   │────▶│  Retriever │────▶│ Generator  │
 └─────────────┘     │ (pgvector) │     │ (OpenAI)   │
                     └────────────┘     └────────────┘
```

### Key design decisions

| Decision | Rationale |
|---|---|
| Full documents stored (`raw_markdown` + `rendered_text`) | Source of truth; chunks are derived, not a replacement |
| Flat sections (not nested) | Simpler schema; section boundaries are already meaningful for retrieval |
| HNSW index (not IVFFlat) | No training step required; better recall on small–medium datasets |
| Chunk linked list (`prev`/`next`) | Context expansion without extra JOIN queries |
| OpenAI Responses API | Simpler stateless usage; `output_text` shorthand |
| Per-file commit-hash change detection | Re-ingest only what changed; scales to large wikis |

---

## Project Structure

```
wiki-rag/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── ask.py          # POST /ask
│   │   │   └── ingest.py       # POST /ingest
│   │   └── schemas.py          # Pydantic request/response models
│   ├── chunking/
│   │   └── chunker.py          # Paragraph-aware token-budget chunking
│   ├── embeddings/
│   │   └── embedder.py         # Batched OpenAI embeddings
│   ├── generation/
│   │   └── generator.py        # OpenAI Responses API answer generation
│   ├── ingestion/
│   │   ├── cloner.py           # Git clone/pull
│   │   ├── detector.py         # Incremental change detection
│   │   └── pipeline.py         # Full ingestion orchestration
│   ├── models/
│   │   └── db_models.py        # SQLAlchemy ORM (Document, Section, Chunk, Asset)
│   ├── parsing/
│   │   └── markdown_parser.py  # Markdown → sections + assets
│   ├── retrieval/
│   │   └── retriever.py        # Vector search + context expansion
│   ├── utils/
│   │   └── logging.py          # Structured logging
│   ├── config.py               # Pydantic settings (env vars)
│   ├── database.py             # Async SQLAlchemy engine + session
│   └── main.py                 # FastAPI app factory
├── alembic/
│   ├── versions/
│   │   └── 001_initial_schema.py  # DB schema + HNSW index
│   └── env.py
├── cli/
│   └── ingest_cli.py           # CLI for ingestion
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── requirements.txt
└── .env.example
```

---

## Quick Start (Local)

### Prerequisites

- Docker + Docker Compose
- An OpenAI API key

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY and WIKI_REPO_URL
```

### 2. Start services

```bash
docker compose up --build
```

This will:
- Start PostgreSQL 16 with pgvector pre-installed
- Run Alembic migrations (creates tables + HNSW index)
- Start the FastAPI server on `http://localhost:8000`

### 3. Ingest your wiki

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/your-org/your-wiki.git"}'
```

### 4. Ask questions

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I deploy to production?"}'
```

Response:

```json
{
  "answer": "According to the deployment guide...",
  "sources": [
    {
      "document": "Deployment Guide",
      "section": "Production Deployment",
      "snippet": "To deploy to production, first...",
      "similarity": 0.89,
      "path": "Deployment-Guide.md"
    }
  ],
  "total_chunks_retrieved": 5
}
```

---

## API Reference

Browse the interactive docs at `http://localhost:8000/docs`

### `POST /ingest`

| Field | Type | Description |
|---|---|---|
| `repo_url` | string | Git URL of the wiki to ingest |
| `force_all` | bool | Re-ingest all files (default: `false`) |

### `POST /ask`

| Field | Type | Description |
|---|---|---|
| `question` | string | Natural language question |
| `repo_filter` | string? | Restrict search to a specific repo |
| `top_k` | int? | Override number of retrieved chunks |

---

## CLI Usage

```bash
# Ingest a wiki
python -m cli.ingest_cli ingest --repo-url https://github.com/org/wiki.git

# Force full reindex
python -m cli.ingest_cli ingest --repo-url https://github.com/org/wiki.git --force-all

# Preview what would be ingested (no DB writes)
python -m cli.ingest_cli ingest --repo-url https://github.com/org/wiki.git --dry-run

# List all markdown files in a repo
python -m cli.ingest_cli list-files --repo-url https://github.com/org/wiki.git
```

---

## Configuration Reference

All settings are environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required** |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `OPENAI_EMBEDDING_DIMENSIONS` | `1536` | Must match model output dims |
| `OPENAI_CHAT_MODEL` | `gpt-4o` | Generation model |
| `DATABASE_URL` | local asyncpg | Async DB URL (runtime) |
| `DATABASE_URL_SYNC` | local psycopg2 | Sync DB URL (Alembic) |
| `WIKI_REPO_URL` | — | Default wiki URL for CLI |
| `WIKI_CLONE_DIR` | `/tmp/wiki_repos` | Clone destination |
| `RETRIEVAL_TOP_K` | `10` | Chunks retrieved per query |
| `RETRIEVAL_SIMILARITY_THRESHOLD` | `0.5` | Min cosine similarity |
| `CONTEXT_WINDOW_CHUNKS` | `2` | Neighbours per matched chunk |
| `MAX_CHUNK_TOKENS` | `800` | Max tokens per chunk |
| `CHUNK_OVERLAP_TOKENS` | `100` | Overlap between consecutive chunks |

---

## Running Migrations Manually

```bash
# Apply all migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1

# Generate a new migration after model changes
alembic revision --autogenerate -m "add metadata column"
```

---

## Kubernetes (EKS) Deployment Notes

This system is designed for K8s. Key points:

- **StatefulSet** for PostgreSQL, or use **Amazon RDS** + **pgvector extension enabled**.
- **Deployment** for the API (horizontally scalable — no local state).
- Mount `WIKI_CLONE_DIR` as an **EFS PersistentVolumeClaim** so all replicas share the git clone.
- Store `OPENAI_API_KEY` and `DATABASE_URL` in **AWS Secrets Manager** / Kubernetes Secrets.
- Run migrations as a **Kubernetes Job** (init container or pre-deploy hook).
- Use **HPA** to scale the API deployment on CPU/memory.

---

## Extending the System

| Feature | Where to add |
|---|---|
| Multi-tenant / metadata filtering | Add `metadata` JSONB column to `chunks`; filter in `retriever.py` |
| Reranker (cross-encoder) | Post-process `retriever.py` results before passing to `generator.py` |
| Streaming answers | Switch to `client.responses.stream()` in `generator.py`; use FastAPI `StreamingResponse` |
| Webhook-based auto-ingest | Add a `POST /webhook/github` route that calls `run_ingestion` |
| Additional file types (Confluence, Notion) | Implement a new parser in `app/parsing/` + update the pipeline |
