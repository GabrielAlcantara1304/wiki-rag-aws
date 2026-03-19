"""
FastAPI application entry point.

Registers:
  - Lifecycle events (startup / shutdown).
  - API routers (ingest, ask).
  - Health endpoint.
  - Global exception handler for unhandled errors.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import ask, gaps, ingest, upload
from app.api.schemas import HealthResponse
from app.config import settings
from app.utils.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


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

    # CORS — restrict origins in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_env == "development" else [],
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
