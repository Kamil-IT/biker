import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "cache.db"
_conn: Optional[sqlite3.Connection] = None


def init_cache() -> None:
    global _conn
    db_existed = _DB_PATH.exists()
    _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    if db_existed:
        row = _conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cache'"
        ).fetchone()
        table_existed = row is not None
    else:
        table_existed = False
    if not table_existed:
        _conn.execute(
            """
            CREATE TABLE cache (
                endpoint    TEXT NOT NULL,
                request     TEXT NOT NULL,
                response    TEXT NOT NULL,
                time_stored TEXT NOT NULL,
                UNIQUE(endpoint, request)
            )
            """
        )
        _conn.commit()
        logger.info("cache table created | path=%s", _DB_PATH)
    else:
        logger.info(
            "cache loaded | path=%s rows=%d",
            _DB_PATH,
            _conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0],
        )


def close_cache() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _normalise(fields: dict) -> str:
    return json.dumps(
        {k: v.strip().lower() for k, v in fields.items()},
        sort_keys=True,
        separators=(",", ":"),
    )


T = TypeVar("T", bound=BaseModel)


def get_cached(endpoint: str, fields: dict, model_cls: Type[T]) -> Optional[T]:
    assert _conn is not None
    row = _conn.execute(
        "SELECT response FROM cache WHERE endpoint = ? AND request = ?",
        (endpoint, _normalise(fields)),
    ).fetchone()
    if row is None:
        logger.info("cache miss | endpoint=%s", endpoint)
        return None
    logger.info("cache hit  | endpoint=%s", endpoint)
    return model_cls.model_validate_json(row[0])


def set_cached(endpoint: str, fields: dict, response: BaseModel) -> None:
    assert _conn is not None
    try:
        _conn.execute(
            "INSERT OR IGNORE INTO cache (endpoint, request, response, time_stored) VALUES (?, ?, ?, ?)",
            (
                endpoint,
                _normalise(fields),
                response.model_dump_json(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        _conn.commit()
        logger.info("cache store | endpoint=%s", endpoint)
    except sqlite3.Error as exc:
        logger.warning("cache store failed (non-fatal) | %s", exc)
