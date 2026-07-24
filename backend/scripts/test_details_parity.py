"""TODO-019 — blob vs ORM parity for bike details.

Reads the same 9 bikes through the old `bike_details_cache` blob path and the
new `bike_details` + `bike_detail_photos` ORM path and asserts the two
`BikeDetailsResponse` objects are equal field for field.

NOTE — deliberate departure from the task file. TODO-019 says "this test is
deleted together with the blob path once green". It is kept instead, and the
blob reader is a ~15-line local copy of the old `store.get_bike_details`
(`_blob_get_bike_details` below) rather than an import from `app.store`, whose
details helpers this task removes. Two reasons: the test stays runnable after
the cutover, and it becomes a permanent regression test for the ORM read path
(casing echo, photo ordering, empty-photo handling, non-ASCII keys, TTL) rather
than a disposable one-off. Nothing here imports the code being deleted.

Everything runs against a COPY of the pre-migration `cache.db` in the
scratchpad, so staleness can be forced without touching real data. The copy is
migrated by `scripts/migrate_bike_details.py` with the blob-table DROP disabled,
so both read paths exist side by side on the same file.

Run:  pytest scripts/test_details_parity.py -v
"""
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402
from app.schemas import BikeDetailsResponse  # noqa: E402

# The pre-migration snapshot: a copy of the real cache.db taken before the
# migration ran, so it still carries all 9 `bike_details_cache` rows. Override
# with TODO019_SNAPSHOT_DB when running elsewhere.
import os  # noqa: E402

import tempfile  # noqa: E402


def _has_blob_tables(path: Path) -> bool:
    """A usable snapshot still carries the legacy blob tables to compare against."""
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('bike_details_cache', 'search_cache')"
            )
        }
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return "bike_details_cache" in names


def _resolve_snapshot() -> Path:
    """Locate a pre-migration `cache.db` to measure parity against.

    This suite is the cutover gate, so a missing fixture is an ERROR, not a
    reason to pass. It deliberately does NOT use `pytest.mark.skipif`: a gate
    that reports "skipped, exit 0" on a fresh clone or in CI announces success
    for doing nothing, which is worse than having no gate at all.
    """
    candidates: list[Path] = []
    env = os.environ.get("TODO019_SNAPSHOT_DB")
    if env:
        candidates.append(Path(env))
    # Committed/derivable locations, in preference order.
    candidates.append(BACKEND_DIR / "tests" / "fixtures" / "cache_pre_migration.db")
    candidates.append(BACKEND_DIR / "cache_pre_migration.db")
    # The live DB is usable only while it still has the blob tables.
    candidates.append(BACKEND_DIR / "cache.db")

    for candidate in candidates:
        if _has_blob_tables(candidate):
            return candidate

    raise RuntimeError(
        "TODO-019 parity gate cannot run: no pre-migration snapshot found.\n"
        "Looked in:\n  " + "\n  ".join(str(c) for c in candidates) + "\n"
        "A usable snapshot is a copy of cache.db taken BEFORE "
        "scripts/migrate_bike_details.py --drop-legacy ran, so it still has the "
        "`bike_details_cache` table.\n"
        "Set TODO019_SNAPSHOT_DB=<path> or place one at "
        "backend/tests/fixtures/cache_pre_migration.db.\n"
        "This is deliberately a hard error, not a skip: these tests gate the "
        "blob-to-ORM cutover, and a gate that silently passes is worse than none."
    )


SNAPSHOT_DB = _resolve_snapshot()
WORK_DIR = Path(
    os.environ.get("TODO019_WORK_DIR")
    or Path(tempfile.gettempdir()) / "todo019-parity"
)
WORK_DIR.mkdir(parents=True, exist_ok=True)

DETAILS_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days — matches both layers

# The 9 rows in `bike_details_cache`, as stored (normalised: stripped + lowercased).
BIKE_PAIRS = [
    ("specialized", "allez sprint"),
    ("trek", "fx 3"),
    ("trek", "fx 3 disc"),
    ("riese & müller", "nevo4 gt"),
    ("trek", "marlin 5"),
    ("trek", "marlin 7"),
    ("cannondale", "topstone carbon 4"),
    ("giant", "revolt advanced pro"),
    ("canyon", "grizl cf 7 esc"),
]

# Both paths key on strip().lower(), so any casing must resolve to the same row
# — and both must echo back whatever the caller passed.
CASINGS = {
    "lower": lambda s: s,
    "title": lambda s: s.title(),
}


# ── blob read path (local copy of the removed store.get_bike_details) ──────

def _blob_get_bike_details(db_path: Path, company: str, model: str) -> Optional[BikeDetailsResponse]:
    """Read `bike_details_cache` exactly as `app/store.py` used to.

    Keyed on strip().lower(); freshness from time_stored + ttl; the response
    echoes the CALLER's casing, not the stored casing.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT description, components, photos, time_stored, ttl "
            "FROM bike_details_cache WHERE company = ? AND model = ?",
            (company.strip().lower(), model.strip().lower()),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    description, components, photos, time_stored, ttl = row
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(time_stored)).total_seconds()
    if age >= ttl:
        return None
    return BikeDetailsResponse.model_validate(
        {
            "company": company,
            "model": model,
            "description": json.loads(description),
            "components": json.loads(components),
            "photos": json.loads(photos),
        }
    )


# ── fixture plumbing ──────────────────────────────────────────────────────

_current_db: Optional[Path] = None


def _point_orm_at(db_path: Path) -> None:
    """Redirect the ORM session factory at a specific DB file.

    `models.get_engine()` hardcodes `backend/cache.db`, so the only way to aim
    the repository at a throwaway copy is to replace the module globals it
    memoises. `repository` calls `get_session()` per operation, so this takes
    effect immediately. Re-pointing per read keeps the tests order-independent:
    the staleness fixture uses its own file and must not leak into the rest.
    """
    global _current_db
    if _current_db == db_path:
        return
    if models._engine is not None:
        models._engine.dispose()
    models.configure_db(db_path)
    _current_db = db_path


def _migrate(db_path: Path) -> None:
    """Run the one-off migration against `db_path`, keeping the blob table.

    `drop_blob_table=False` is what leaves both read paths on the same file.
    """
    import scripts.migrate_bike_details as migration  # noqa: PLC0415

    migration.migrate(db_path=db_path, drop_blob_table=False, verbose=False)


def _assert_schema_current(db_path: Path) -> None:
    """Every column the ORM declares must exist in the file.

    A copy migrated by an older script (or not migrated at all) would otherwise
    blow up mid-query with an opaque OperationalError instead of failing here
    with a readable message. Derived from the model, so it keeps up with schema
    changes (e.g. normalised lookup columns) without editing this test.
    """
    from app.models import Bike, BikeDetails, BikeDetailPhoto  # noqa: PLC0415

    conn = sqlite3.connect(str(db_path))
    try:
        for table in (Bike, BikeDetails, BikeDetailPhoto):
            name = table.__tablename__
            present = {
                row[1] for row in conn.execute(f"PRAGMA table_info({name})").fetchall()
            }
            assert present, f"table {name!r} missing from {db_path.name}"
            declared = {c.name for c in table.__table__.columns}
            missing = declared - present
            assert not missing, (
                f"{name} is missing column(s) {sorted(missing)} — the fixture DB predates "
                f"the current schema; re-run scripts/migrate_bike_details.py"
            )
    finally:
        conn.close()


def _prepare(name: str) -> Path:
    """Fresh copy of the pre-migration snapshot, migrated, ORM pointed at it."""
    global _current_db
    dst = WORK_DIR / name
    _assert_disposable(dst)
    if models._engine is not None:
        models._engine.dispose()
    _current_db = None  # the file is about to be replaced — force a new engine
    for suffix in ("", "-wal", "-shm"):
        stale = Path(str(dst) + suffix)
        if stale.exists():
            stale.unlink()
    shutil.copy2(SNAPSHOT_DB, dst)
    _point_orm_at(dst)
    _migrate(dst)
    _assert_schema_current(dst)
    return dst


def _assert_disposable(db_path: Path) -> None:
    """Refuse to touch anything that is not a throwaway copy.

    These tests force TTL expiry and write rows, so pointing them at a real
    `cache.db` would corrupt live data. The fixture DBs live in the scratchpad;
    a checked-out repo tree is never a valid target.
    """
    resolved = db_path.resolve()
    assert resolved.parent == WORK_DIR.resolve(), (
        f"refusing to use {resolved} — fixture DBs must live in {WORK_DIR}"
    )
    assert not resolved.is_relative_to(BACKEND_DIR.resolve()), (
        f"refusing to use {resolved} — it is inside the project tree, and these "
        f"tests force TTL expiry and write rows"
    )
    assert resolved != SNAPSHOT_DB.resolve(), \
        "refusing to mutate the snapshot itself — work on a copy"


@pytest.fixture(scope="module")
def parity_db() -> Path:
    """Shared migrated copy for the read-parity tests (never made stale)."""
    return _prepare("parity_work.db")


@pytest.fixture(scope="module")
def stale_db() -> Path:
    """Own copy with every row forced past its TTL, so expiry cannot leak into
    the read-parity tests."""
    db = _prepare("parity_stale.db")
    expired = datetime.now(timezone.utc) - timedelta(seconds=DETAILS_TTL_SECONDS + 86400)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("UPDATE bike_details_cache SET time_stored = ?", (expired.isoformat(),))
        # SQLAlchemy stores DateTime as a naive 'YYYY-MM-DD HH:MM:SS.ffffff' string.
        conn.execute(
            "UPDATE bike_details SET updated_at = ?",
            (expired.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f"),),
        )
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture()
def scratch_db() -> Path:
    """Own copy for tests that rename existing rows, which would otherwise
    invalidate the shared read-parity fixture."""
    return _prepare("parity_scratch.db")


def _orm_get(db_path: Path, company: str, model: str) -> Optional[BikeDetailsResponse]:
    from app import repository  # noqa: PLC0415 — imported late, after _point_orm_at

    _point_orm_at(db_path)
    return repository.get_bike_details(company, model)


# ── migration shape ───────────────────────────────────────────────────────

def test_migration_moved_all_nine_rows(parity_db: Path) -> None:
    conn = sqlite3.connect(str(parity_db))
    try:
        blob_rows = conn.execute("SELECT COUNT(*) FROM bike_details_cache").fetchone()[0]
        orm_rows = conn.execute("SELECT COUNT(*) FROM bike_details").fetchone()[0]
        photo_rows = conn.execute("SELECT COUNT(*) FROM bike_detail_photos").fetchone()[0]
        blob_photos = sum(
            len(json.loads(p)) for (p,) in conn.execute("SELECT photos FROM bike_details_cache")
        )
    finally:
        conn.close()
    assert blob_rows == 9, f"snapshot should hold 9 blob rows, has {blob_rows}"
    assert orm_rows == 9, f"expected 9 rows in bike_details, got {orm_rows}"
    assert photo_rows == blob_photos, (
        f"bike_detail_photos has {photo_rows} rows but the blob rows hold {blob_photos} photos"
    )


def test_migration_is_idempotent(parity_db: Path) -> None:
    """Re-running the migration must change nothing (acceptance criterion)."""
    def counts() -> tuple[int, int, int]:
        conn = sqlite3.connect(str(parity_db))
        try:
            return tuple(
                conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("bikes", "bike_details", "bike_detail_photos")
            )
        finally:
            conn.close()

    before = counts()
    before_payload = [_orm_get(parity_db, c, m) for c, m in BIKE_PAIRS]
    _migrate(parity_db)
    assert counts() == before, f"re-running the migration changed row counts: {before} → {counts()}"
    assert [_orm_get(parity_db, c, m) for c, m in BIKE_PAIRS] == before_payload, \
        "re-running the migration changed the payload read back through the ORM"


# ── field-for-field parity ────────────────────────────────────────────────

@pytest.mark.parametrize("casing", list(CASINGS))
@pytest.mark.parametrize(("company", "model"), BIKE_PAIRS, ids=lambda v: v.replace(" ", "_"))
def test_blob_and_orm_agree(parity_db: Path, company: str, model: str, casing: str) -> None:
    cast = CASINGS[casing]
    asked_company, asked_model = cast(company), cast(model)

    blob = _blob_get_bike_details(parity_db, asked_company, asked_model)
    orm = _orm_get(parity_db, asked_company, asked_model)

    assert blob is not None, f"blob path missed {asked_company!r}/{asked_model!r}"
    assert orm is not None, (
        f"ORM path missed {asked_company!r}/{asked_model!r} — case-insensitive lookup regressed"
    )

    # Caller-casing echo (D2): both paths return what was passed in, not what is stored.
    assert blob.company == asked_company and blob.model == asked_model
    assert orm.company == asked_company, (
        f"ORM echoed stored casing {orm.company!r}, expected caller's {asked_company!r}"
    )
    assert orm.model == asked_model, (
        f"ORM echoed stored casing {orm.model!r}, expected caller's {asked_model!r}"
    )

    # Full BikeDescription object, not just its text.
    assert orm.description == blob.description

    # Full component tree, including nested SpecItem ordering.
    assert len(orm.components) == len(blob.components)
    for orm_cat, blob_cat in zip(orm.components, blob.components):
        assert orm_cat == blob_cat, f"component category diverged: {blob_cat.name!r}"
    assert orm.components == blob.components

    # Same URLs in the same order.
    assert orm.photos == blob.photos

    assert orm == blob, "BikeDetailsResponse objects differ"


def test_empty_photos_round_trip_as_list(parity_db: Path) -> None:
    """`specialized`/`allez sprint` has photos = "[]" — zero photo rows must
    deserialise back to [], never None."""
    orm = _orm_get(parity_db, "specialized", "allez sprint")
    assert orm is not None
    assert orm.photos is not None, "empty photos came back as None"
    assert orm.photos == [], f"expected [], got {orm.photos!r}"


def test_non_ascii_key_round_trips(parity_db: Path) -> None:
    """`riese & müller` must survive the backfill and the case-folded lookup."""
    blob = _blob_get_bike_details(parity_db, "riese & müller", "nevo4 gt")
    orm = _orm_get(parity_db, "riese & müller", "nevo4 gt")
    assert blob is not None and orm is not None, "non-ASCII key lost in migration"
    assert orm == blob


# ── revised D1: normalised lookup, not SQL lower() ────────────────────────
# SQLite's lower() is ASCII-only. Measured on this build:
#
#   Riese & Müller   sqlite='riese & müller'  python='riese & müller'  agree=True
#   RIESE & MÜLLER   sqlite='riese & mÜller'  python='riese & müller'  agree=False
#   Riese & MÜller   sqlite='riese & mÜller'  python='riese & müller'  agree=False
#   Škoda            sqlite='Škoda'           python='škoda'           agree=False
#   ŠKODA            sqlite='Škoda'           python='škoda'           agree=False
#
# It takes an UPPERCASE non-ASCII character to break `func.lower(...)`. The
# canonical `Riese & Müller` spelling case-folds identically in both engines, so
# a title-case test of it proves nothing — it passes under the broken design
# too. These tests use the spellings that genuinely diverge.

def test_uppercase_non_ascii_lookup_hits(parity_db: Path) -> None:
    """THE regression case for revised D1.

    `riese & müller`/`nevo4 gt` asked for as `"RIESE & MÜLLER"` must HIT. Under
    a `func.lower(Bike.brand) == company.lower()` comparison it cannot: SQLite
    reduces the stored value to 'riese & müller' but leaves the caller's 'Ü'
    alone, so the two sides never meet.
    """
    orm = _orm_get(parity_db, "RIESE & MÜLLER", "NEVO4 GT")
    assert orm is not None, (
        "MISS on 'RIESE & MÜLLER'/'NEVO4 GT' — non-ASCII case-folding is broken. "
        "SQLite lower() does not fold 'Ü' to 'ü'; the lookup needs normalised "
        "brand_norm/model_norm columns rather than func.lower()"
    )
    assert orm.company == "RIESE & MÜLLER", f"expected caller casing, got {orm.company!r}"
    assert orm.model == "NEVO4 GT", f"expected caller casing, got {orm.model!r}"
    # Same row as the canonical spelling, payload included.
    canonical = _orm_get(parity_db, "riese & müller", "nevo4 gt")
    assert canonical is not None
    assert orm.components == canonical.components and orm.photos == canonical.photos, \
        "upper-case and canonical spellings resolved to different data"


def test_leading_non_ascii_capital_brand_round_trips(parity_db: Path) -> None:
    """A `Škoda`-style brand: the very first character is an uppercase non-ASCII
    letter, so *every* spelling of it diverges between SQLite and Python — even
    the one a user would type naturally. Synthetic, because no such brand is in
    the fixture data.
    """
    from app import repository  # noqa: PLC0415

    _point_orm_at(parity_db)
    seed = _orm_get(parity_db, "trek", "fx 3")
    assert seed is not None, "fixture bike missing"

    repository.save_bike_details("Škoda", "Ŝprint ÅRO", seed)

    for company, model in [
        ("Škoda", "Ŝprint ÅRO"),   # exactly as saved
        ("škoda", "ŝprint åro"),   # all lower
        ("ŠKODA", "ŜPRINT ÅRO"),   # all upper
        ("ŠkOdA", "ŝPRINT åro"),   # mixed
    ]:
        got = _orm_get(parity_db, company, model)
        assert got is not None, (
            f"MISS on {company!r}/{model!r} — a brand starting with an uppercase "
            f"non-ASCII letter is unreachable; SQLite lower() cannot fold it"
        )
        assert got.company == company and got.model == model, \
            f"expected caller casing {company!r}/{model!r}, got {got.company!r}/{got.model!r}"
        assert got.components == seed.components

    assert len(_bike_rows(parity_db, "škoda", "ŝprint åro")) == 1, \
        "the non-ASCII brand split into multiple identity rows"


@pytest.mark.parametrize(
    ("company", "model"),
    [
        ("riese & müller", "nevo4 gt"),
        ("Riese & Müller", "Nevo4 GT"),
        ("RIESE & MÜLLER", "NEVO4 GT"),
        ("Riese & MÜller", "nEvO4 gT"),
        ("  riese & müller  ", "  nevo4 gt  "),
    ],
)
def test_mixed_case_non_ascii_resolves_to_one_row(
    parity_db: Path, company: str, model: str
) -> None:
    """Every casing of the same non-ASCII key resolves to the same single row."""
    canonical = _orm_get(parity_db, "riese & müller", "nevo4 gt")
    assert canonical is not None, "canonical lowercase lookup missed"
    got = _orm_get(parity_db, company, model)
    assert got is not None, f"MISS on {company!r}/{model!r} — case folding is broken"
    assert got.company == company and got.model == model, \
        f"expected caller casing {company!r}/{model!r}, got {got.company!r}/{got.model!r}"
    assert got.components == canonical.components and got.photos == canonical.photos, \
        f"{company!r}/{model!r} resolved to a different row than the canonical spelling"


def _bike_rows(db_path: Path, brand: str, model: str) -> list[tuple]:
    """Every `bikes` row whose brand+model case-folds to this key (Python-side,
    so the count is independent of whatever collation the schema uses)."""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT id, brand, model FROM bikes").fetchall()
    finally:
        conn.close()
    want = (brand.strip().lower(), model.strip().lower())
    return [r for r in rows if (r[1].strip().lower(), r[2].strip().lower()) == want]


def test_resave_with_different_casing_creates_no_duplicate_identity(parity_db: Path) -> None:
    """Task item 2: a differently-cased spelling must reuse the existing `bikes`
    row, not split the identity in two. Asserted on the row count directly."""
    from app import repository  # noqa: PLC0415

    _point_orm_at(parity_db)
    before = _bike_rows(parity_db, "riese & müller", "nevo4 gt")
    assert len(before) == 1, f"expected exactly 1 identity row to start, found {len(before)}"

    payload = _orm_get(parity_db, "riese & müller", "nevo4 gt")
    assert payload is not None
    repository.save_bike_details("RIESE & MÜLLER", "Nevo4 GT", payload)

    after = _bike_rows(parity_db, "riese & müller", "nevo4 gt")
    assert len(after) == 1, (
        f"case-split identity: saving 'RIESE & MÜLLER'/'Nevo4 GT' created a second "
        f"bikes row — now {len(after)}: {after}"
    )
    assert after[0][0] == before[0][0], "the identity row id changed"

    # Same for an ASCII bike, where SQL lower() does work — guards the reverse
    # regression once the lookup moves to normalised columns.
    ascii_before = _bike_rows(parity_db, "trek", "marlin 7")
    assert len(ascii_before) == 1
    trek = _orm_get(parity_db, "trek", "marlin 7")
    assert trek is not None
    repository.save_bike_details("TREK", "Marlin 7", trek)
    assert len(_bike_rows(parity_db, "trek", "marlin 7")) == 1, \
        "case-split identity on an ASCII bike"


def test_save_search_reuses_identity_across_casing(parity_db: Path) -> None:
    """`save_search` is the second site that mints `bikes` rows.

    It must go through the same normalised get-or-create as `save_bike_details`,
    or a search result spelled differently from the details row splits the
    identity in two. Covers the ASCII and the uppercase-non-ASCII case.
    """
    from app import repository  # noqa: PLC0415
    from app.schemas import BikeResult as BikeResultSchema  # noqa: PLC0415

    _point_orm_at(parity_db)

    def _result(brand: str, model: str) -> BikeResultSchema:
        return BikeResultSchema(
            brand=brand, model=model, accessories=["parity fixture"],
            match_score=8.0, explanation="seeded by test_save_search_reuses_identity",
        )

    for stored_brand, stored_model, odd_brand, odd_model in [
        ("trek", "marlin 5", "TREK", "Marlin 5"),
        ("riese & müller", "nevo4 gt", "RIESE & MÜLLER", "NEVO4 GT"),
    ]:
        before = _bike_rows(parity_db, stored_brand, stored_model)
        assert len(before) == 1, f"expected 1 identity row for {stored_brand}, got {before}"

        repository.save_search("parity fixture query", [_result(odd_brand, odd_model)])

        after = _bike_rows(parity_db, stored_brand, stored_model)
        assert len(after) == 1, (
            f"save_search({odd_brand!r}, {odd_model!r}) minted a duplicate identity row — "
            f"now {len(after)}: {after}"
        )
        assert after[0][0] == before[0][0], "save_search changed the identity row id"
        # The stored casing is the original one — save_search must not rewrite it.
        assert (after[0][1], after[0][2]) == (before[0][1], before[0][2]), \
            "save_search overwrote the stored brand/model casing"


def test_norm_columns_track_reassignment(scratch_db: Path) -> None:
    """`brand_norm` must follow `brand` when the attribute is reassigned.

    `Bike.__init__` fills both `_norm` columns at construction, so the insert
    path is safe — but `__init__` does not fire on later attribute assignment,
    so `bike.brand = "..."` leaves `brand_norm` pointing at the old value and
    the row becomes unfindable under its new name. Expected to fail until the
    model uses `@validates('brand', 'model')` (or an equivalent hook).
    """
    from app.models import Bike, BikeDetails, norm  # noqa: PLC0415

    _point_orm_at(scratch_db)
    session = models.get_session()
    try:
        # Must be a bike that HAS a details row: `bikes` also holds identities
        # imported from search results, which have no details, and looking one
        # of those up returns None for a reason that has nothing to do with
        # norm tracking.
        bike = (
            session.query(Bike)
            .join(BikeDetails, BikeDetails.bike_id == Bike.id)
            .filter(Bike.brand_norm == "trek")
            .first()
        )
        assert bike is not None, "no Trek row with details to exercise"
        bike.brand = "Trék Bicycle CORP"
        bike.model = "Márlin ÜBER"
        session.commit()
        session.refresh(bike)
        assert bike.brand_norm == norm("Trék Bicycle CORP"), (
            f"brand_norm went stale after reassignment: {bike.brand_norm!r} != "
            f"{norm('Trék Bicycle CORP')!r} — the model needs @validates on brand/model"
        )
        assert bike.model_norm == norm("Márlin ÜBER"), (
            f"model_norm went stale after reassignment: {bike.model_norm!r}"
        )
    finally:
        session.close()

    # And the renamed bike is reachable under its new name, in any casing.
    assert _orm_get(scratch_db, "TRÉK BICYCLE CORP", "MÁRLIN ÜBER") is not None, \
        "renamed bike unreachable — brand_norm did not follow the rename"


def test_distinct_models_stay_distinct(parity_db: Path) -> None:
    """`Canyon`/`Grizl CF 7` and `Canyon`/`Grizl` are different bikes: the
    normalised unique index must not collapse them into one identity.

    Written against freshly saved rows rather than the pre-existing test-script
    leftovers of the same names, because `migrate_bike_details.cleanup()`
    deletes those two as orphan `bikes` rows (task item 2 says they may go).
    """
    from app import repository  # noqa: PLC0415

    _point_orm_at(parity_db)
    payload = _orm_get(parity_db, "canyon", "grizl cf 7 esc")
    assert payload is not None

    repository.save_bike_details("Canyon", "Grizl CF 7", payload)
    repository.save_bike_details("Canyon", "Grizl", payload)

    long_rows = _bike_rows(parity_db, "canyon", "grizl cf 7")
    short_rows = _bike_rows(parity_db, "canyon", "grizl")
    assert len(long_rows) == 1, f"expected 1 row for Canyon/Grizl CF 7, got {long_rows}"
    assert len(short_rows) == 1, f"expected 1 row for Canyon/Grizl, got {short_rows}"
    assert long_rows[0][0] != short_rows[0][0], (
        "Canyon/Grizl CF 7 and Canyon/Grizl were merged into a single bikes row — "
        "the unique index is over-normalising"
    )
    # And the third, genuinely different model is untouched.
    assert len(_bike_rows(parity_db, "canyon", "grizl cf 7 esc")) == 1

    for company, model in [("Canyon", "Grizl CF 7"), ("Canyon", "Grizl")]:
        got = _orm_get(parity_db, company, model)
        assert got is not None, f"{company}/{model} not readable after save"
        assert got.company == company and got.model == model


# ── TTL ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("company", "model"), BIKE_PAIRS, ids=lambda v: v.replace(" ", "_"))
def test_stale_row_returns_none_from_both_paths(
    stale_db: Path, company: str, model: str
) -> None:
    """Both timestamps are past the TTL on this copy; neither path may serve it."""
    assert _blob_get_bike_details(stale_db, company, model) is None, "blob served a stale row"
    assert _orm_get(stale_db, company, model) is None, "ORM served a stale row"
