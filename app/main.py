"""
FastAPI application entry point.

Registers:
  - Lifecycle events (startup / shutdown).
  - API routers (ingest, ask).
  - Health endpoint.
  - Global exception handler for unhandled errors.

In production (APP_ENV=production), secrets are loaded from AWS Secrets Manager
before Settings() is instantiated, so DATABASE_URL and OPENAI_API_KEY are
available as env vars by the time the app boots.
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.utils.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load secrets from AWS Secrets Manager before Settings() is instantiated.
# In development, AWS_SECRET_NAME is empty so this is a no-op.
# ---------------------------------------------------------------------------
_secret_name = os.environ.get("AWS_SECRET_NAME", "")
_aws_region = os.environ.get("AWS_REGION", "us-east-1")
if _secret_name:
    from app.aws.secrets import load_secrets_into_env
    load_secrets_into_env(_secret_name, _aws_region)

from app.api.routes import ask, gaps, ingest, upload  # noqa: E402 — must follow secret injection
from app.api.schemas import HealthResponse  # noqa: E402
from app.config import settings  # noqa: E402 — must follow secret injection
from app.retrieval.reranker import _get_model  # noqa: E402


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="Wiki RAG API",
        description=(
            "Internal AI assistant powered by a GitHub Wiki. "
            "Ingest your wiki once, then ask questions in natural language."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    allowed_origins = ["*"] if settings.app_env == "development" else settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------------------

    @app.on_event("startup")
    async def startup() -> None:
        logger.info(
            "Wiki RAG API starting (env=%s, model=%s)",
            settings.app_env, settings.openai_chat_model,
        )
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _get_model)
        logger.info("Reranker model warm-up complete.")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        logger.info("Wiki RAG API shutting down")

    # ---------------------------------------------------------------------------
    # Routes
    # ---------------------------------------------------------------------------

    app.include_router(ingest.router, tags=["Ingestion"])
    app.include_router(upload.router, tags=["Ingestion"])
    app.include_router(gaps.router, tags=["Gaps"])
    app.include_router(ask.router, tags=["Q&A"])

    app.mount("/ui", StaticFiles(directory="frontend", html=True), name="frontend")

    @app.get("/health", response_model=HealthResponse, tags=["System"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    # ---------------------------------------------------------------------------
    # Global error handler — returns JSON instead of HTML for 500s
    # ---------------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception on %s %s: %s", request.method, request.url, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred. See server logs for details."},
        )

    return app


app = create_app()
