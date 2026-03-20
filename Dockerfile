FROM python:3.11-slim

WORKDIR /app

# Install git (required for wiki cloning)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer caching)
COPY requirements.txt .
# Install torch CPU-only first to avoid pulling the 2GB CUDA version
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user (uid 1000) so libraries like torch can resolve the username
RUN addgroup --gid 1000 appuser \
 && adduser --uid 1000 --gid 1000 --no-create-home --disabled-password --gecos "" appuser

# Copy application code
COPY --chown=appuser:appuser . .

USER 1000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
