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

# Create non-root user with home dir so HuggingFace cache works
RUN addgroup --gid 1000 appuser \
 && adduser --uid 1000 --gid 1000 --home /home/appuser --disabled-password --gecos "" appuser

# Pre-download reranker model into the image (avoids runtime download + permission issues)
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512)"

# Copy application code
COPY --chown=appuser:appuser . .

USER 1000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
