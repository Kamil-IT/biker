"""Database access for the bike discovery scripts (TODO-035, TODO-039).

Re-uses the backend's engine, models and repository: puts `<repo>/backend` on
sys.path and loads `backend/.env` *before* `app.models` is imported (the engine
reads DATABASE_URL / PGPASSFILE lazily, but other modules read them on import).
"""
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load_env(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding what is already set."""
    if not path.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env(BACKEND_DIR / ".env")

from sqlalchemy import (  # noqa: E402
    Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, inspect,
)
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session, validates  # noqa: E402

from app import models, repository  # noqa: E402,F401

SOURCE = "centrumrowerowe.pl"

PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"
STATUSES = (PENDING, IN_PROGRESS, DONE, FAILED, SKIPPED)

NORM_LEN = 255


def utcnow() -> datetime:
    """Timezone-aware UTC, like the backend models' `datetime.now(timezone.utc)` defaults."""
    return datetime.now(timezone.utc)


def norm(value: Optional[str]) -> str:
    """The bike identity form: `strip().lower()` in Python, like the backend's `repository._lc`.

    Never SQL lower() — SQLite's is ASCII-only. Cut to the column size.
    """
    return (value or "").strip().lower()[:NORM_LEN]


class BikeDiscovery(models.Base):
    """One bike waiting to be turned into a `bike` + `bike_detail` row, and its processing state.

    Identity = (company_norm, model_norm): a bike listed twice (by one shop or several) is one
    row with several listings. The norm columns follow company/model through `@validates` on
    construction and assignment — a Core `update()` bypasses it and must set them itself.
    """

    __tablename__ = "bike_discovery"
    __table_args__ = (
        UniqueConstraint("company_norm", "model_norm", name="uq_bike_discovery_identity"),
        Index("ix_bike_discovery_status_next_attempt", "status", "next_attempt_at"),
    )

    id = Column(Integer, primary_key=True)
    company = Column(String(255), nullable=False)
    model = Column(String(255), nullable=False)
    company_norm = Column(String(NORM_LEN), nullable=False)
    model_norm = Column(String(NORM_LEN), nullable=False)
    bike_type = Column(String(64), nullable=True)
    bike_id = Column(Integer, ForeignKey("bike.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(16), nullable=False, default=PENDING, server_default=PENDING)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    @validates("company", "model")
    def _sync_norm(self, key, value):
        setattr(self, f"{key}_norm", norm(value))
        return value


class BikeDiscoveryListing(models.Base):
    """One product in one shop, linked to the bike it lists."""

    __tablename__ = "bike_discovery_listing"
    __table_args__ = (
        UniqueConstraint("source", "source_product_id", name="uq_bike_discovery_listing_source_product"),
        Index("ix_bike_discovery_listing_discovery", "discovery_id"),
        Index("ix_bike_discovery_listing_source_seen", "source", "last_seen_at"),
    )

    id = Column(Integer, primary_key=True)
    discovery_id = Column(Integer, ForeignKey("bike_discovery.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(50), nullable=False)
    source_product_id = Column(String(64), nullable=False)
    raw_name = Column(String(512), nullable=False)
    details_link = Column(String(2048), nullable=True)
    price = Column(String(100), nullable=True)
    first_seen_at = Column(DateTime, nullable=False, default=utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    fetched_at = Column(DateTime, nullable=True)  # last attempt to fetch this page
    fetch_error = Column(Text, nullable=True)     # its error; NULL after a fetch that parsed


TABLES = (BikeDiscovery.__table__, BikeDiscoveryListing.__table__)
OLD_LAYOUT_MESSAGE = ("bike_discovery still has the TODO-036 layout (shop columns on the bike row) — "
                      "run migrate_discovery_listings.py first")


def has_old_layout(bind=None) -> bool:
    """True when `bike_discovery` exists with its pre-TODO-039 `source` column."""
    insp = inspect(bind if bind is not None else models.get_engine())
    if not insp.has_table(BikeDiscovery.__tablename__):
        return False
    return "source" in {c["name"] for c in insp.get_columns(BikeDiscovery.__tablename__)}


def ensure_table() -> None:
    """Create `bike_discovery` + `bike_discovery_listing` on the current engine if missing.

    Refuses (SystemExit) a database whose `bike_discovery` still has the old layout: creating
    the listing table next to it would only hide the missing migration.
    """
    engine = models.get_engine()
    if has_old_layout(engine):
        raise SystemExit(OLD_LAYOUT_MESSAGE)
    for table in TABLES:
        table.create(engine, checkfirst=True)


@contextmanager
def session():
    """A Session bound to the backend's *current* engine (follows `configure_db`)."""
    s = Session(bind=models.get_engine())
    try:
        yield s
    finally:
        s.close()


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
PROXY_PORT = 6543  # host port of the Cloud SQL proxy (points at the prod database)


def describe_target(url: str, allow_remote: bool = False) -> str:
    """Render `url` with the password hidden; SystemExit unless it is a local database.

    Local = SQLite, or a localhost host on a port other than the Cloud SQL proxy's 6543.
    Pure URL logic - never connects.
    """
    parsed = make_url(url)
    shown = parsed.render_as_string(hide_password=True)
    if parsed.get_backend_name() == "sqlite":
        return shown
    local = (parsed.host or "") in LOCAL_HOSTS and parsed.port != PROXY_PORT
    if not local and not allow_remote:
        raise SystemExit(
            f"Refusing to write to a non-local database: {shown} "
            f"(host {parsed.host!r}, port {parsed.port}; port {PROXY_PORT} is the Cloud SQL proxy). "
            "Pass --allow-remote only if you really mean to."
        )
    return shown


def check_target(allow_remote: bool = False) -> str:
    """describe_target() for the backend's current engine URL."""
    return describe_target(models.get_engine().url.render_as_string(hide_password=False), allow_remote)
