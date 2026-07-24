"""TODO-019 phase 2 — blob vs ORM parity for cached searches.

Mirrors `test_details_parity.py` for the search half: reads every cached search
through the old `search_cache` blob path and the new `searches` + `bike_results`
+ `accessories` ORM path and asserts they agree field for field **including
result order**, which is the whole risk of the migration — the blob preserved
ordering for free as a JSON array, a row set does not.

Per D9 the blob readers below are local copies of the helpers this task removes
from `app/store.py`, not imports from it. Fixture plumbing is shared with
`test_details_parity.py` rather than duplicated.

ONE DELIBERATE DIFFERENCE, asserted rather than ignored: the blob stored a
bike's brand/model as free text, so the same bike appeared under several
spellings; the ORM stores one identity row and every result references it. A
blob search holding `TREK`/`MARLIN 5` therefore reads back as `Trek`/`Marlin 5`.
Parity is asserted case-insensitively on brand/model and exactly on everything
else, plus an explicit assertion that the difference is *only* casing.

Run:  pytest scripts/test_search_parity.py -v
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.schemas import BikeResult as BikeResultSchema  # noqa: E402
from scripts.test_details_parity import (  # noqa: E402
    SNAPSHOT_DB,
    _bike_rows,
    _point_orm_at,
    _prepare,
)

SEARCH_TTL_SECONDS = 24 * 60 * 60


def _norm(text: str) -> str:
    return text.strip().lower()


# ── blob read path (local copies of the removed store.py helpers) ──────────

def _blob_get_search_by_query(db_path: Path, query: str) -> Optional[list[BikeResultSchema]]:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT bikes, time_stored, ttl FROM search_cache WHERE query = ?",
            (_norm(query),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    bikes_json, time_stored, ttl = row
    if not _blob_is_fresh(time_stored, ttl):
        return None
    return [BikeResultSchema.model_validate(b) for b in json.loads(bikes_json)]


def _blob_is_fresh(time_stored: str, ttl: int) -> bool:
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(time_stored)).total_seconds()
    return age < ttl


def _blob_all_rows(db_path: Path) -> list[tuple[str, str, str, int]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT query, bikes, time_stored, ttl FROM search_cache"
        ).fetchall()
    finally:
        conn.close()


def _blob_find_bikes_by_brand(db_path: Path, brand: str) -> list[BikeResultSchema]:
    needle = _norm(brand)
    matches: list[BikeResultSchema] = []
    seen: set[tuple[str, str]] = set()
    for _query, bikes_json, time_stored, ttl in _blob_all_rows(db_path):
        if not _blob_is_fresh(time_stored, ttl):
            continue
        for b in json.loads(bikes_json):
            if _norm(b.get("brand", "")) != needle:
                continue
            key = (_norm(b.get("brand", "")), _norm(b.get("model", "")))
            if key in seen:
                continue
            seen.add(key)
            matches.append(BikeResultSchema.model_validate(b))
    return matches


def _blob_find_bike_by_brand_model(
    db_path: Path, brand: str, model: str
) -> list[BikeResultSchema]:
    want = (_norm(brand), _norm(model))
    matches: list[BikeResultSchema] = []
    seen: set[tuple[str, str]] = set()
    for _query, bikes_json, time_stored, ttl in _blob_all_rows(db_path):
        if not _blob_is_fresh(time_stored, ttl):
            continue
        for b in json.loads(bikes_json):
            key = (_norm(b.get("brand", "")), _norm(b.get("model", "")))
            if key != want or key in seen:
                continue
            seen.add(key)
            matches.append(BikeResultSchema.model_validate(b))
    return matches


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def search_db() -> Path:
    """Migrated copy of the pre-migration snapshot, blob tables retained."""
    return _prepare("search_parity.db")


@pytest.fixture()
def stale_search_db() -> Path:
    """Own copy so forced expiry cannot leak into the read-parity tests."""
    return _prepare("search_parity_stale.db")


@pytest.fixture()
def seeded_search_db(request: pytest.FixtureRequest) -> Path:
    """Own copy for tests that WRITE searches.

    `save_search` adds rows to `searches`/`bikes`, which would make the
    row-count and parity assertions on the shared fixture depend on test
    execution order — they would pass only while the writing tests happen to run
    last. Isolating them keeps every test independent.

    The filename is per-test: on Windows a just-disposed SQLite engine can still
    hold the file, so re-preparing one shared path fails with a PermissionError
    in the second test's setup.
    """
    return _prepare(f"search_parity_seeded_{request.node.name}.db")


def _orm(db_path: Path):
    from app import repository  # noqa: PLC0415

    _point_orm_at(db_path)
    return repository


def _blob_queries(db_path: Path) -> list[str]:
    return [q for q, _b, _t, _ttl in _blob_all_rows(db_path)]


def _assert_same_bike(
    orm_bike: BikeResultSchema, blob_bike: BikeResultSchema, where: str
) -> None:
    """Field for field, INCLUDING casing.

    Casing is asserted exactly, not just identity. The placeholder-upgrade bug
    (search results rendering as `cannondale`/`topstone carbon 4` because the
    details migration seeded `bikes` from the old blob's lowercased keys) would
    sail through any set-equality or id-based check — the identities were right,
    only the display casing was wrong, and it is `bikes.brand`/`model` that the
    UI renders. Verified 0/75 mismatches on a clean migration of the snapshot.
    """
    assert orm_bike.brand == blob_bike.brand, (
        f"{where}: brand casing differs — ORM {orm_bike.brand!r} vs blob {blob_bike.brand!r}"
        + (" (identity matches, so this is the placeholder-upgrade regression: a bike "
           "identity was seeded from a lowercased blob key and never upgraded)"
           if _norm(orm_bike.brand) == _norm(blob_bike.brand) else "")
    )
    assert orm_bike.model == blob_bike.model, (
        f"{where}: model casing differs — ORM {orm_bike.model!r} vs blob {blob_bike.model!r}"
        + (" (identity matches — placeholder-upgrade regression)"
           if _norm(orm_bike.model) == _norm(blob_bike.model) else "")
    )
    assert orm_bike.accessories == blob_bike.accessories, (
        f"{where}: accessories differ (order matters) — "
        f"ORM {orm_bike.accessories!r} vs blob {blob_bike.accessories!r}"
    )
    assert orm_bike.match_score == blob_bike.match_score, f"{where}: match_score differs"
    assert orm_bike.explanation == blob_bike.explanation, f"{where}: explanation differs"


# ── the migration itself ──────────────────────────────────────────────────

def test_every_blob_search_migrated(search_db: Path) -> None:
    conn = sqlite3.connect(str(search_db))
    try:
        blob_rows = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        searches = conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
        blob_results = sum(
            len(json.loads(b)) for (b,) in conn.execute("SELECT bikes FROM search_cache")
        )
        orm_results = conn.execute(
            "SELECT COUNT(*) FROM bike_results WHERE search_id IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    assert blob_rows > 0, "snapshot has no search_cache rows — fixture is not exercising anything"
    assert searches == blob_rows, f"expected {blob_rows} searches, got {searches}"
    assert orm_results == blob_results, (
        f"expected {blob_results} bike_results, got {orm_results}"
    )


def test_search_migration_is_idempotent(search_db: Path) -> None:
    import scripts.migrate_bike_details as migration  # noqa: PLC0415

    repo = _orm(search_db)
    before = {q: repo.get_search_by_query(q) for q in _blob_queries(search_db)}
    stats = migration.migrate(db_path=search_db, drop_blob_table=False, verbose=False)
    assert stats["searches"] == 0, f"re-run wrote {stats['searches']} searches, expected 0"
    assert stats["results"] == 0, f"re-run wrote {stats['results']} results, expected 0"
    repo = _orm(search_db)
    assert {q: repo.get_search_by_query(q) for q in _blob_queries(search_db)} == before, \
        "re-running the migration changed what reads back"


# ── get_search_by_query parity, including order ───────────────────────────

def test_get_search_by_query_parity_all_rows(search_db: Path) -> None:
    """Every cached search, field for field, in order."""
    repo = _orm(search_db)
    queries = _blob_queries(search_db)
    assert queries, "no search_cache rows to compare"

    compared = 0
    for query in queries:
        blob = _blob_get_search_by_query(search_db, query)
        orm = repo.get_search_by_query(query)
        if blob is None:
            # A stale blob row must be stale on the ORM side too.
            assert orm is None, f"{query!r}: blob stale but ORM returned {orm!r}"
            continue
        assert orm is not None, f"{query!r}: ORM missed a search the blob serves"
        assert len(orm) == len(blob), (
            f"{query!r}: {len(orm)} results vs blob {len(blob)}"
        )
        for i, (orm_bike, blob_bike) in enumerate(zip(orm, blob)):
            _assert_same_bike(orm_bike, blob_bike, f"{query!r}[{i}]")
        compared += 1
    assert compared > 0, "every blob row was stale — this test proved nothing"


def test_result_order_is_preserved_exactly(search_db: Path) -> None:
    """The ordering guarantee, asserted on its own.

    `position` is the only thing standing between the ORM and an arbitrary row
    order, and the 5 bikes are allocated by score weight, so order is meaningful.
    Compares the full (brand, model) sequence, not just set membership.
    """
    repo = _orm(search_db)
    checked = 0
    for query in _blob_queries(search_db):
        blob = _blob_get_search_by_query(search_db, query)
        if blob is None or len(blob) < 2:
            continue  # a 0- or 1-result search cannot demonstrate ordering
        orm = repo.get_search_by_query(query)
        assert orm is not None
        assert [(_norm(b.brand), _norm(b.model)) for b in orm] == \
               [(_norm(b.brand), _norm(b.model)) for b in blob], \
            f"{query!r}: result order diverged from the blob array order"
        checked += 1
    assert checked > 0, "no multi-result search available — ordering was never exercised"


def test_position_matches_blob_array_index(search_db: Path) -> None:
    """`position` must literally be the blob's array index, not just sorted."""
    conn = sqlite3.connect(str(search_db))
    try:
        rows = conn.execute(
            "SELECT s.query, r.position, b.brand_norm, b.model_norm "
            "FROM bike_results r "
            "JOIN searches s ON s.id = r.search_id "
            "JOIN bikes b ON b.id = r.bike_id"
        ).fetchall()
        blob = {q: json.loads(bj) for q, bj in
                conn.execute("SELECT query, bikes FROM search_cache")}
    finally:
        conn.close()

    by_query: dict[str, dict[int, tuple[str, str]]] = {}
    for query, position, brand_norm, model_norm in rows:
        by_query.setdefault(query, {})[position] = (brand_norm, model_norm)

    assert by_query, "no migrated results to check"
    for query, positions in by_query.items():
        expected = blob.get(query)
        assert expected is not None, f"{query!r} in searches but not in search_cache"
        assert sorted(positions) == list(range(len(expected))), (
            f"{query!r}: positions {sorted(positions)} are not 0..{len(expected) - 1} — "
            f"gaps or duplicates in the ordering column"
        )
        for idx, entry in enumerate(expected):
            assert positions[idx] == (_norm(entry["brand"]), _norm(entry["model"])), (
                f"{query!r}: position {idx} holds {positions[idx]}, "
                f"blob array index {idx} holds "
                f"{(_norm(entry['brand']), _norm(entry['model']))}"
            )


# ── lookup-by-attribute parity ────────────────────────────────────────────

def _brands_in_snapshot(db_path: Path) -> list[str]:
    brands: set[str] = set()
    for _q, bikes_json, _t, _ttl in _blob_all_rows(db_path):
        for b in json.loads(bikes_json):
            if b.get("brand"):
                brands.add(b["brand"])
    return sorted(brands)


def test_find_bikes_by_brand_parity(search_db: Path) -> None:
    repo = _orm(search_db)
    brands = _brands_in_snapshot(search_db)
    assert brands, "no brands in the snapshot"
    for brand in brands:
        blob = _blob_find_bikes_by_brand(search_db, brand)
        orm = repo.find_bikes_by_brand(brand)
        blob_ids = sorted((_norm(b.brand), _norm(b.model)) for b in blob)
        orm_ids = sorted((_norm(b.brand), _norm(b.model)) for b in orm)
        assert orm_ids == blob_ids, (
            f"find_bikes_by_brand({brand!r}): ORM {orm_ids} vs blob {blob_ids}"
        )


def test_find_bike_by_brand_model_parity(search_db: Path) -> None:
    repo = _orm(search_db)
    pairs: set[tuple[str, str]] = set()
    for _q, bikes_json, _t, _ttl in _blob_all_rows(search_db):
        for b in json.loads(bikes_json):
            pairs.add((b.get("brand", ""), b.get("model", "")))
    assert pairs, "no (brand, model) pairs in the snapshot"
    for brand, model in sorted(pairs):
        blob = _blob_find_bike_by_brand_model(search_db, brand, model)
        orm = repo.find_bike_by_brand_model(brand, model)
        assert sorted((_norm(b.brand), _norm(b.model)) for b in orm) == \
               sorted((_norm(b.brand), _norm(b.model)) for b in blob), \
            f"find_bike_by_brand_model({brand!r}, {model!r}) diverged"


def test_find_bikes_by_brand_is_exact_not_substring(search_db: Path) -> None:
    """Ruling 3: the ORM's old `ilike('%brand%')` became an exact `brand_norm`
    match. That is a real behaviour change for `GET /v1/bike/search-cache?brand=`
    — a prefix no longer matches. Asserting the NEW contract deliberately.
    """
    repo = _orm(search_db)
    brands = {_norm(b) for b in _brands_in_snapshot(search_db)}
    target = "trek"
    assert target in brands, "snapshot has no Trek bikes to test against"

    assert repo.find_bikes_by_brand("Trek"), "exact match (title case) must hit"
    assert repo.find_bikes_by_brand("trek"), "exact match (lower case) must hit"
    assert repo.find_bikes_by_brand("  TREK  "), "exact match must survive case + padding"

    # Substring/prefix must NOT match any more.
    for near_miss in ["Tre", "rek", "Trekker", "Trek Bicycle"]:
        if _norm(near_miss) in brands:
            continue  # would be a legitimate exact hit
        assert repo.find_bikes_by_brand(near_miss) == [], (
            f"find_bikes_by_brand({near_miss!r}) matched — the lookup is still doing "
            f"substring matching, but ruling 3 requires an exact brand_norm match"
        )


# ── TTL ───────────────────────────────────────────────────────────────────

def test_stale_search_returns_none_from_both_paths(stale_search_db: Path) -> None:
    """Expiry lives on the parent `searches` row; both paths must honour it."""
    expired = datetime.now(timezone.utc) - timedelta(seconds=SEARCH_TTL_SECONDS + 3600)
    conn = sqlite3.connect(str(stale_search_db))
    try:
        conn.execute("UPDATE search_cache SET time_stored = ?", (expired.isoformat(),))
        conn.execute(
            "UPDATE searches SET created_at = ?",
            (expired.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f"),),
        )
        conn.commit()
    finally:
        conn.close()

    repo = _orm(stale_search_db)
    queries = _blob_queries(stale_search_db)
    assert queries, "no rows to expire"
    for query in queries:
        assert _blob_get_search_by_query(stale_search_db, query) is None, \
            f"{query!r}: blob served a stale search"
        assert repo.get_search_by_query(query) is None, \
            f"{query!r}: ORM served a stale search"

    # Lookup-by-attribute must also drop results whose parent search expired.
    for brand in _brands_in_snapshot(stale_search_db)[:5]:
        assert repo.find_bikes_by_brand(brand) == [], \
            f"find_bikes_by_brand({brand!r}) returned results from an expired search"


# ── case collision + the casing-upgrade rule ──────────────────────────────

def test_case_colliding_search_reuses_existing_identities(seeded_search_db: Path) -> None:
    """A search whose bikes collide case-wise with existing `bikes` rows must
    reference those rows, not mint duplicates."""
    repo = _orm(seeded_search_db)

    def _result(brand: str, model: str) -> BikeResultSchema:
        return BikeResultSchema(
            brand=brand, model=model, accessories=["collision probe"],
            match_score=7.5, explanation="seeded by search parity",
        )

    before_trek = _bike_rows(seeded_search_db, "trek", "marlin 5")
    before_rm = _bike_rows(seeded_search_db, "riese & müller", "nevo4 gt")
    assert len(before_trek) == 1 and len(before_rm) == 1, "expected one identity row each"

    repo.save_search(
        "case collision probe",
        [_result("TREK", "MARLIN 5"), _result("RIESE & MÜLLER", "NEVO4 GT")],
    )

    after_trek = _bike_rows(seeded_search_db, "trek", "marlin 5")
    after_rm = _bike_rows(seeded_search_db, "riese & müller", "nevo4 gt")
    assert len(after_trek) == 1, f"duplicate Trek identity minted: {after_trek}"
    assert len(after_rm) == 1, f"duplicate Riese & Müller identity minted: {after_rm}"
    assert after_trek[0][0] == before_trek[0][0], "Trek identity id changed"
    assert after_rm[0][0] == before_rm[0][0], "Riese & Müller identity id changed"

    stored = repo.get_search_by_query("case collision probe")
    assert stored is not None and len(stored) == 2, "the probe search did not round-trip"
    assert [(_norm(b.brand), _norm(b.model)) for b in stored] == [
        ("trek", "marlin 5"), ("riese & müller", "nevo4 gt"),
    ], "collision probe lost its order or its identities"


def test_placeholder_casing_upgrades_but_never_downgrades(seeded_search_db: Path) -> None:
    """The casing rule from the 9-mismatch bug.

    A stored value equal to its own normalised form carries no casing
    information and is a placeholder: the first writer with real casing upgrades
    it. The rule must be monotonic — an all-lowercase write must never overwrite
    real casing, or two writers oscillate forever.
    """
    repo = _orm(seeded_search_db)

    def _result(brand: str, model: str) -> BikeResultSchema:
        return BikeResultSchema(
            brand=brand, model=model, accessories=["casing probe"],
            match_score=6.0, explanation="seeded by casing probe",
        )

    # Seed a pure-placeholder identity (all lowercase, as the blob keys were).
    repo.save_search("casing probe seed", [_result("bianchi", "oltre xr4")])
    seeded = _bike_rows(seeded_search_db, "bianchi", "oltre xr4")
    assert len(seeded) == 1, f"expected 1 row, got {seeded}"
    assert (seeded[0][1], seeded[0][2]) == ("bianchi", "oltre xr4"), \
        f"placeholder not stored as written: {seeded[0]}"

    # A writer with real casing upgrades the placeholder in place.
    repo.save_search("casing probe upgrade", [_result("Bianchi", "Oltre XR4")])
    upgraded = _bike_rows(seeded_search_db, "bianchi", "oltre xr4")
    assert len(upgraded) == 1, f"upgrade minted a duplicate identity: {upgraded}"
    assert upgraded[0][0] == seeded[0][0], "upgrade changed the identity row id"
    assert (upgraded[0][1], upgraded[0][2]) == ("Bianchi", "Oltre XR4"), (
        f"real casing did not upgrade the placeholder: {upgraded[0]}"
    )

    # And an all-lowercase writer must NOT undo it — this is the monotonicity.
    repo.save_search("casing probe downgrade", [_result("bianchi", "oltre xr4")])
    final = _bike_rows(seeded_search_db, "bianchi", "oltre xr4")
    assert len(final) == 1, f"downgrade attempt minted a duplicate: {final}"
    assert (final[0][1], final[0][2]) == ("Bianchi", "Oltre XR4"), (
        f"an all-lowercase write downgraded real casing to {final[0][1:]!r} — "
        f"the upgrade rule is not monotonic and two writers will oscillate"
    )
