# Backend image — the same image runs under docker compose and on Cloud Run (TODO-029/030).
# No secrets inside: ANTHROPIC_API_KEY and DATABASE_URL come from the environment at runtime.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_HEADLESS=true \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && patchright install --with-deps chromium

RUN useradd --create-home --uid 1000 biker
COPY --chown=biker:biker app ./app
COPY --chown=biker:biker scripts/copy_sqlite_to_postgres.py ./scripts/
USER biker

EXPOSE 8000
# Cloud Run injects $PORT; compose and local runs fall back to 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
