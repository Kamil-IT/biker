"""Environment configuration for the searcher, read once at import.

Values come from the process environment first and searcher/.env second
(python-dotenv never overrides a variable that is already set, so docker
compose / Cloud Run settings win over the file):

  SEARCHER_API_KEY         shared secret expected in X-Searcher-Key; unset = every request is 401
  DATABASE_URL             REQUIRED SQLAlchemy URL of the shared bike DB — no SQLite fallback here
  CLAUDE_BIN               path to the claude CLI; unset = whatever `claude` resolves to on PATH
  SEARCHER_CLAUDE_MODEL    model passed to `claude --model` (default claude-haiku-4-5-20251001)
  SEARCHER_CLI_TIMEOUT     seconds one CLI run may take before it is killed (default 300)
  SEARCHER_MAX_CONCURRENT  CLI runs (each with its own browser) allowed at once (default 1)
  PLAYWRIGHT_HEADLESS      true = no browser window (Docker / server); unset = visible browser
  CLAUDE_CODE_OAUTH_TOKEN  read by the CLI itself on a server (`claude setup-token`); never logged
"""
import logging
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

from .browser_config import playwright_headless  # noqa: F401 — re-exported for callers

logger = logging.getLogger("searcher.config")

ROOT_DIR = Path(__file__).resolve().parent.parent  # searcher/
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

load_dotenv(ROOT_DIR / ".env")

DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_CLI_TIMEOUT = 300.0
DEFAULT_MAX_CONCURRENT = 1


def _env_number(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid %s=%r — using %s", name, raw, default)
        return default


SEARCHER_API_KEY = os.getenv("SEARCHER_API_KEY", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
CLAUDE_MODEL = os.getenv("SEARCHER_CLAUDE_MODEL", "").strip() or DEFAULT_CLAUDE_MODEL
CLI_TIMEOUT = max(1.0, _env_number("SEARCHER_CLI_TIMEOUT", DEFAULT_CLI_TIMEOUT))
MAX_CONCURRENT = max(1, int(_env_number("SEARCHER_MAX_CONCURRENT", DEFAULT_MAX_CONCURRENT)))


def database_url() -> str:
    """The DB URL, or a RuntimeError naming the fix — the searcher has no SQLite fallback."""
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set — the searcher writes into the shared bike database and "
            "refuses to start without it (e.g. postgresql+psycopg://biker:biker@localhost:5432/biker)"
        )
    return DATABASE_URL


def safe_database_url() -> str:
    """The DB URL with its password masked — the only form that may be logged."""
    try:
        return make_url(database_url()).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 — an unparsable URL must not leak either
        return "<invalid DATABASE_URL>"


def claude_binary() -> str | None:
    """Absolute path of the claude CLI: $CLAUDE_BIN, else `claude` on PATH (claude.exe on Windows)."""
    explicit = os.getenv("CLAUDE_BIN", "").strip()
    if explicit:
        return explicit if Path(explicit).exists() else shutil.which(explicit)
    return shutil.which("claude")
