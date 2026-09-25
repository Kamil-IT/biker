# Searcher image — the same image runs under docker compose and on Cloud Run (TODO-031).
# No secrets inside: CLAUDE_CODE_OAUTH_TOKEN, SEARCHER_API_KEY and DATABASE_URL come from the
# environment at runtime. Modelled on backend/Dockerfile, plus Node 24 for the claude CLI.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_HEADLESS=true \
    DISABLE_AUTOUPDATER=1 \
    PORT=8100

# Node 24 (nodesource) + the Claude Code CLI, which the searcher drives with `claude -p`.
# Pinned: app/claude_cli.py relies on flags proven on this version (--json-schema,
# --permission-prompts, --setting-sources, …); bump deliberately and re-run scripts/test_searcher.py.
ARG CLAUDE_CODE_VERSION=2.1.283
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && patchright install --with-deps chromium

# Non-root, with a writable HOME: the claude CLI keeps its state under ~/.claude.
RUN useradd --create-home --uid 1000 searcher
COPY --chown=searcher:searcher app ./app
USER searcher
ENV HOME=/home/searcher

EXPOSE 8100
# Cloud Run injects $PORT; compose and local runs fall back to 8100.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
