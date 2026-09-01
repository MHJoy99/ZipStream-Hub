# Multi-stage lightweight Dockerfile for ZipStreamHub
# Stage 1: Build stage
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY . /build

RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Final lightweight runtime stage
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ZIPSTREAM_PORT=8787 \
    ZIPSTREAM_HOST=0.0.0.0

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy application source files
COPY . /app

# Create non-root user for security
RUN useradd -m -u 1000 zipstream && \
    chown -R zipstream:zipstream /app

USER zipstream

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/').read()" || exit 1

ENTRYPOINT ["python", "server.py"]
