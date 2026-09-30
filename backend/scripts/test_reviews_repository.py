"""Unit tests for the stored expert review (TODO-037): app/reviews_repository.py
get_review and scripts/copy_review_cache_to_table.py, each on a fresh temp SQLite
database — no server, no network, no AI call.
Run: cd backend && pytest   (collected via pytest.ini)"""
import json
from datetime import datetime
import sys
from pathlib import Path

import pytest
from sqlalchemy import insert, inspect, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models  # noqa: E402
from app.models import Bike, BikeReview, BikeReviewSource, endpoint_req_to_body_cache  # noqa: E402
from app.reviews_repository import EMPTY_REVIEW, get_bike_review, get_review  # noqa: E402
from copy_review_cache_to_table import copy_reviews  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh SQLite database with every table; the ORM points back at its default afterwards."""
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(tmp_path / "reviews.db")
    models.init_db()
    yield
    models.dispose_engine()
    models._db_url = None


def _bike(brand: str, model: str) -> int:
    with models.get_session() as s:
        bike = Bike(brand=brand, model=model)
        s.add(bike)
        s.commit()
        return bike.id


def _review(bike_id: int, ref: list[str], **fields) -> None:
    with models.get_session() as s:
        row = BikeReview(bike_id=bike_id, **{
            "score": 8, "explanation": "Dobry rower.", "rating": 7.5, "sources_used": 3, **fields,
        })
        # Inserted in reverse so the read has to sort by display_order, not by id.
        row.sources = [BikeReviewSource(url=u, display_order=i) for i, u in reversed(list(enumerate(ref)))]
        s.add(row)
        s.commit()


def _cache_row(company: str, model: str, response: dict | str, time_stored="2026-05-01T10:00:00+00:00") -> None:
    request = json.dumps({"company": company.strip().lower(), "model": model.strip().lower()},
                         sort_keys=True, separators=(",", ":"))
    body = response if isinstance(response, str) else json.dumps(response)
    with models.get_engine().begin() as conn:
        conn.execute(insert(endpoint_req_to_body_cache).values(
            endpoint="/v1/bike/review", request=request, response=body, time_stored=time_stored,
        ))


def _stored() -> dict[int, tuple]:
    """bike_id -> (score, explanation, rating, sources_used, [urls in display order])."""
    with models.get_session() as s:
        return {
            r.bike_id: (r.score, r.explanation, r.rating, r.sources_used, [src.url for src in r.sources])
            for r in s.query(BikeReview)
        }


GOOD = {"score": 8, "explanation": "Świetny.", "ref": ["https://t1/a", "https://t2/b", "https://t3/c"],
        "rating": 7.8, "sources_used": 3}


# --- get_review ----------------------------------------------------------


def test_get_review_hit_keeps_display_order_and_matches_case_insensitively(db):
    bike_id = _bike("Riese & Müller", "Charger4")
    _review(bike_id, ["https://tier1/x", "https://tier2/y", "https://tier3/z"])
    got = get_review("  RIESE & MÜLLER ", "charger4")
    assert got.model_dump() == {
        "score": 8, "explanation": "Dobry rower.", "ref": ["https://tier1/x", "https://tier2/y", "https://tier3/z"],
        "rating": 7.5, "sources_used": 3,
    }
    assert get_bike_review is get_review


def test_get_review_unknown_bike_and_bike_without_review_are_empty(db):
    _bike("Trek", "Marlin 5")
    assert get_review("Nope", "Nothing") == EMPTY_REVIEW
    assert get_review("Trek", "Marlin 5") == EMPTY_REVIEW
    assert EMPTY_REVIEW.model_dump() == {"score": 0, "explanation": "", "ref": [], "rating": 0.0, "sources_used": 0}


def test_get_review_db_error_is_empty(db, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("db down")
    monkeypatch.setattr("app.reviews_repository._find_bike_id", boom)
    assert get_review("Trek", "Marlin 5") == EMPTY_REVIEW
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_deleting_bike_cascades_to_review_and_sources(db):
    bike_id = _bike("Trek", "Marlin 5")
    _review(bike_id, ["https://a", "https://b"])
    with models.get_session() as s:
        s.delete(s.get(Bike, bike_id))
        s.commit()
        assert s.execute(select(BikeReview.id)).first() is None
        assert s.execute(select(BikeReviewSource.id)).first() is None


# --- copy_review_cache_to_table ------------------------------------------


def test_copy_reviews_copies_eligible_rows_and_is_idempotent(db):
    trek = _bike("Trek", "Marlin 5")
    giant = _bike("Giant", "Talon 1")
    _cache_row("Trek", "Marlin 5", GOOD)
    _cache_row("Giant", "Talon 1", {**GOOD, "ref": [], "sources_used": 0})       # degenerate: no sources
    _cache_row("Kross", "Level 3.0", GOOD)                                       # bike not in `bike`
    _cache_row("Cube", "Aim", "{not json")                                       # unparseable

    dry = copy_reviews(dry_run=True, verbose=False)
    assert dry["status"] == "dry-run" and dry["copied"] == 1
    assert _stored() == {}, "--dry-run must write nothing"

    report = copy_reviews(verbose=False)
    assert report["status"] == "copied"
    assert {k: report[k] for k in ("copied", "skipped_existing", "skipped_unknown_bike",
                                   "skipped_degenerate", "unparseable")} == {
        "copied": 1, "skipped_existing": 0, "skipped_unknown_bike": 1, "skipped_degenerate": 1, "unparseable": 1,
    }
    assert report["unknown_bikes"] == ["kross / level 3.0"]
    assert _stored() == {trek: (8, "Świetny.", 7.8, 3, GOOD["ref"])}
    assert giant not in _stored()
    with models.get_session() as s:
        row = s.query(BikeReview).one()
        assert (row.created_at.year, row.created_at.month, row.created_at.day) == (2026, 5, 1)

    again = copy_reviews(verbose=False)
    assert again["copied"] == 0 and again["skipped_existing"] == 1
    assert _stored() == {trek: (8, "Świetny.", 7.8, 3, GOOD["ref"])}
    assert get_review("Trek", "Marlin 5").ref == GOOD["ref"]


def test_copy_reviews_keeps_existing_review_unless_forced(db):
    trek = _bike("Trek", "Marlin 5")
    _review(trek, ["https://old"], score=2, explanation="Stara.", rating=2.0, sources_used=1)
    _cache_row("Trek", "Marlin 5", GOOD)

    assert copy_reviews(verbose=False)["skipped_existing"] == 1
    assert _stored()[trek] == (2, "Stara.", 2.0, 1, ["https://old"])

    forced = copy_reviews(force=True, verbose=False)
    assert forced["copied"] == 1
    assert _stored() == {trek: (8, "Świetny.", 7.8, 3, GOOD["ref"])}
    with models.get_session() as s:
        assert s.query(BikeReviewSource).count() == 3, "--force replaces the sources, never appends"


def test_copy_reviews_keeps_only_http_urls(db):
    trek = _bike("Trek", "Marlin 5")
    giant = _bike("Giant", "Talon 1")
    _cache_row("Trek", "Marlin 5", {**GOOD, "ref": [
        "javascript:alert(1)", "https://t1/a", "data:text/html,x", "http:///nohost", "ftp://x/y", "http://t2/b",
    ]})
    _cache_row("Giant", "Talon 1", {**GOOD, "ref": ["javascript:alert(1)", "vbscript:x"]})

    report = copy_reviews(verbose=False)
    assert report["copied"] == 1 and report["skipped_degenerate"] == 1
    assert report["dropped_urls"] == 6
    assert _stored() == {trek: (8, "Świetny.", 7.8, 3, ["https://t1/a", "http://t2/b"])}
    assert giant not in _stored()


def test_copy_reviews_newest_cache_row_wins_and_force_keeps_newer_updated_at(db, tmp_path):
    trek = _bike("Trek", "Marlin 5")
    _cache_row("Trek", "Marlin 5", {**GOOD, "score": 3}, time_stored="2026-01-01T00:00:00+00:00")
    with models.get_engine().begin() as conn:  # same bike under a legacy un-normalised key, newer
        conn.execute(insert(endpoint_req_to_body_cache).values(
            endpoint="/v1/bike/review", request='{"company":" TREK ","model":"Marlin 5"}',
            response=json.dumps({**GOOD, "score": 9}), time_stored="2026-06-01T00:00:00+00:00",
        ))
    report = copy_reviews(verbose=False)
    assert report["copied"] == 1 and report["skipped_existing"] == 1
    assert _stored()[trek][0] == 9

    with models.get_session() as s:
        s.query(BikeReview).update({BikeReview.updated_at: datetime(2026, 9, 1)})
        s.commit()
    copy_reviews(force=True, verbose=False)
    with models.get_session() as s:
        assert s.query(BikeReview.updated_at).scalar() == datetime(2026, 9, 1), "--force must not move updated_at back"


def test_copy_reviews_creates_missing_review_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(tmp_path / "old.db")
    try:
        models.Base.metadata.create_all(models.get_engine(), tables=[models.Bike.__table__, endpoint_req_to_body_cache])
        _bike("Trek", "Marlin 5")
        _cache_row("Trek", "Marlin 5", GOOD)
        assert copy_reviews(dry_run=True, verbose=False)["copied"] == 1
        assert not inspect(models.get_engine()).has_table("bike_review"), "--dry-run creates nothing"
        assert copy_reviews(verbose=False)["copied"] == 1
        assert get_review("Trek", "Marlin 5").ref == GOOD["ref"]
    finally:
        models.dispose_engine()
        models._db_url = None


def test_copy_reviews_url_rule_matches_searcher(db):
    trek = _bike("Trek", "Marlin 5")
    _cache_row("Trek", "Marlin 5", {**GOOD, "ref": [
        "https://escapecollective.com/r", "https://www.Velominati.com/x", "https://news.escapecollective.com/y",
        "https://notvelominati.com/ok", "https://t1/" + "a" * 2048, " https://t1/space", "https://t1/a",
    ]})
    report = copy_reviews(verbose=False)
    assert report["dropped_urls"] == 5
    assert _stored()[trek][4] == ["https://notvelominati.com/ok", "https://t1/a"]
