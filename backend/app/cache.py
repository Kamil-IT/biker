import json
import logging
from datetime import datetime, timezone
from typing import Optional, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from .models import dialect_insert, dispose_engine, endpoint_req_to_body_cache, get_engine

logger = logging.getLogger(__name__)

# Generic per-endpoint response cache. The table is declared in app/models.py
# and created by init_db(); every read/write goes through the shared SQLAlchemy
# engine, so it lives in whichever database DATABASE_URL selects (TODO-028).
_table = endpoint_req_to_body_cache


def init_cache() -> None:
    """Startup hook: log where the cache lives. Call after models.init_db()."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(select(func.count()).select_from(_table)).scalar_one()
    logger.info(
        "cache loaded | db=%s rows=%d",
        engine.url.render_as_string(hide_password=True), rows,
    )


def close_cache() -> None:
    dispose_engine()


def _normalise(fields: dict) -> str:
    return json.dumps(
        {k: v.strip().lower() for k, v in fields.items()},
        sort_keys=True,
        separators=(",", ":"),
    )


T = TypeVar("T", bound=BaseModel)


def get_cached(endpoint: str, fields: dict, model_cls: Type[T]) -> Optional[T]:
    with get_engine().connect() as conn:
        response = conn.execute(
            select(_table.c.response).where(
                _table.c.endpoint == endpoint,
                _table.c.request == _normalise(fields),
            )
        ).scalar_one_or_none()
    if response is None:
        logger.info("cache miss | endpoint=%s", endpoint)
        return None
    logger.info("cache hit  | endpoint=%s", endpoint)
    return model_cls.model_validate_json(response)


def set_cached(endpoint: str, fields: dict, response: BaseModel) -> None:
    # First write wins — the old INSERT OR IGNORE, portable across dialects.
    stmt = dialect_insert(_table).values(
        endpoint=endpoint,
        request=_normalise(fields),
        response=response.model_dump_json(),
        time_stored=datetime.now(timezone.utc).isoformat(),
    ).on_conflict_do_nothing(index_elements=["endpoint", "request"])
    try:
        with get_engine().begin() as conn:
            conn.execute(stmt)
        logger.info("cache store | endpoint=%s", endpoint)
    except SQLAlchemyError as exc:
        logger.warning("cache store failed (non-fatal) | %s", exc)
