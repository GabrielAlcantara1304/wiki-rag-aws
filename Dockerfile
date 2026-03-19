FROM python:3.11-slim

WORKDIR /app

# Install git (required for wiki cloning) and curl (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Run as non-root user (security best practice)
RUN useradd -m -u 1000 appuser

# Install Python dependencies first (layer caching)
COPY requirements.txt .
# Install torch CPU-only to avoid pulling the 2GB CUDA version
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser . .

USER appuser

# Healthcheck — used by EKS liveness/readiness probes via HTTP
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Migrations run at startup; EKS init containers or Jobs are preferred in prod
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
