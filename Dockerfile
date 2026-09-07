# ============================================
# KIS Strategy & Alert Server - Dockerfile
# ============================================

FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency files and README
COPY pyproject.toml uv.lock* README.md ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY templates ./templates
COPY static ./static

# Install project
RUN uv sync --frozen --no-dev

# Non-root runtime user
# ⚠️ HOME이 KIS 토큰 캐시 경로를 결정한다.
#    src/adapters/external/kis_api/auth.py 의 `Path.home() / "KIS" / "config"`
#    docker-compose.yml 의 kis_token_cache 마운트 경로와 반드시 일치시킬 것.
RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --home-dir /home/appuser --create-home appuser \
    && mkdir -p /home/appuser/KIS/config /home/appuser/.cache/uv \
    && chown -R 10001:10001 /home/appuser \
    && chmod 700 /home/appuser/KIS/config

ENV HOME=/home/appuser \
    UV_CACHE_DIR=/home/appuser/.cache/uv

USER 10001:10001

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
# ⚠️ `uv run`은 기동 시 /app/.venv를 재동기화하려 하므로 비루트에서 실패한다
#    (error: failed to remove file '/app/.venv/.../_editable_impl_*.pth': Permission denied).
#    venv 바이너리를 직접 실행한다. PYTHONPATH=/app 은 위에서 이미 설정됨.
#    컨테이너 내부 일회성 명령도 `uv run ...` 대신 `/app/.venv/bin/<cmd>` 를 쓸 것.
CMD ["/app/.venv/bin/uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
