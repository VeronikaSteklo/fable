FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS python-build
# Poetry stays in this build stage; the runtime receives only the application venv.
RUN pip install --no-cache-dir poetry==2.4.1 \
    && python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    POETRY_NO_INTERACTION=1
WORKDIR /build
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    POETRY_REQUESTS_TIMEOUT=120 POETRY_INSTALLER_MAX_WORKERS=4 \
    poetry install --only main --no-root --no-ansi
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FABLE_HOST=0.0.0.0 \
    FABLE_PORT=8000 \
    FABLE_FRONTEND_DIST=/app/frontend/dist \
    MEMORY_STORE_PATH=/data/chroma \
    SESSIONS_PATH=/data/sessions \
    AUTH_DB_PATH=/data/fable.db
RUN groupadd --gid 10001 fable \
    && useradd --uid 10001 --gid fable --create-home fable \
    && mkdir -p /data/chroma /data/sessions \
    && chown -R fable:fable /data
WORKDIR /app
COPY --from=python-build /opt/venv /opt/venv
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist
USER fable
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('FABLE_PORT', '8000') + '/openapi.json', timeout=4).close()"]
CMD ["fable-server"]
