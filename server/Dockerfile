# Jikimi AI server image: FastAPI API + workers + the static dashboard (multi-stage, slim).
# Build from the repository root: docker build -f server/Dockerfile -t jikimi/server .

FROM node:26-slim AS web
WORKDIR /web
COPY apps/dashboard/package.json apps/dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/dashboard/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.12-slim-trixie AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# WeasyPrint (Pango/HarfBuzz) + Urdu Nastaliq/Naskh fonts for the bilingual evidence PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-noto-core fonts-noto-extra fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY server/ server/
COPY edge/pyproject.toml edge/pyproject.toml
COPY edge/src/ edge/src/
COPY ml/pyproject.toml ml/pyproject.toml
COPY ml/src/ ml/src/
RUN uv sync --frozen --no-dev --package jikimi-server --extra postgres
COPY --from=web /web/out /app/apps/dashboard/out
ENV PATH="/app/.venv/bin:$PATH" JIKIMI_DASHBOARD_DIR=/app/apps/dashboard/out JIKIMI_DATA_DIR=/data
RUN useradd --system --uid 10001 jikimi && mkdir -p /data && chown jikimi /data
USER jikimi
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD curl -fsS http://127.0.0.1:8000/v1/health || exit 1
CMD ["uvicorn", "jikimi_server.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
