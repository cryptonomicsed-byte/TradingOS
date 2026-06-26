FROM python:3.11-slim

WORKDIR /app

# Build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir \
    "fastapi>=0.111.0" "uvicorn[standard]>=0.30.0" "asyncpg>=0.29.0" \
    "redis[asyncio]>=5.0.0" "qdrant-client[fastembed]>=1.9.0" \
    "python-jose[cryptography]>=3.3.0" "pydantic>=2.7.0" \
    "structlog>=24.0.0" "python-dotenv>=1.0.0" "httpx>=0.27.0"

# Pre-download the embedding model so it's baked into the image
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')" || true

COPY app.py .

EXPOSE 7704

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:7704/health || exit 1

CMD ["python", "app.py"]
