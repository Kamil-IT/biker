"""migrate_discovery_listings.py on a temp SQLite file in the TODO-036 layout — never a real database."""
from datetime import timedelta

import pytest
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.exc import IntegrityError

import migrate_discovery_listings as mdl
from conftest import OLD_BIKE_DISCOVERY, old_row
from db import (
    DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, SOURCE, BikeDiscovery, BikeDiscoveryListing, ensure_table, models,
    session, utcnow,
)


def add_bikes(*names) -> list[int]:
    """`bike` rows (the FK target of bike_discovery.bike_id)."""
    with session() as s:
        bikes = [models.Bike(brand=b, model=m) for b, m in names]
        s.add_all(bikes)
        s.commit()
        return [b.id for b in bikes]


def dump() -> dict:
    """Schema + every row of the discovery tables (whatever layout they have)."""
    engine = models.get_engine()
    with engine.connect() as conn:
        schema = sorted(conn.execute(text(
            "SELECT type, name, sql FROM sqlite_master WHERE tbl_name LIKE 'bike_discovery%'")).all())
        out = {"schema": schema}
        for name in inspect(conn).get_table_names():
            if name.startswith("bike_discovery"):
                t = Table(name, MetaData(), autoload_with=conn)
                out[name] = conn.execute(select(t).order_by(t.c.id)).all()
    return out


def columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(models.get_engine()).get_columns(table)}


def bike_by_norm(company_norm, model_norm) -> BikeDiscovery:
    with session() as s:
        row = s.query(BikeDiscovery).filter_by(company_norm=company_norm, model_norm=model_norm).one()
        s.expunge(row)
        return row


def listings() -> dict[str, BikeDiscoveryListing]:
    with session() as s:
        rows = s.query(BikeDiscoveryListing).all()
        for r in rows:
            s.expunge(r)
        return {r.source_product_id: r for r in rows}


@pytest.fixture
def seeded(old_layout_db):
    """Plain pending, done with bike_id, a done + pending pair collapsing to one identity, a failed row."""
    wagant_id, hexagon_id = add_bikes(("Romet", "Wagant 3"), ("Kross", "Hexagon 2"))
    now = utcnow().replace(tzinfo=None)
    ids = old_layout_db(
        old_row("pd1", company="KROSS", model="Level 1"),
        old_row("pd2", status=DONE, bike_id=wagant_id, attempts=1, company="Romet", price="2199.00"),
        old_row("pd3", company="KROSS", model="Hexagon 2 ", last_seen_at=now - timedelta(days=2)),  # pending, lower id
        old_row("pd4", company="Kross", model="hexagon 2", status=DONE, bike_id=hexagon_id, attempts=2),
        old_row("pd5", company="ROMET", model="Orkan", status=FAILED, attempts=2, last_error="ParseError: x",
                next_attempt_at=now + timedelta(hours=6)),
    )
    return {"ids": dict(zip(("pd1", "pd2", "pd3", "pd4", "pd5"), ids)), "wagant": wagant_id, "hexagon": hexagon_id}


def test_migration_moves_every_row_into_a_listing(seeded):
    before = dump()["bike_discovery"]
    old = {r.source_product_id: r for r in before}
    result = mdl.migrate(verbose=False)
    assert result == {"status": mdl.MIGRATED, "old_rows": 5, "bikes": 4, "listings": 5, "merged_groups": 1,
                      "merged_rows": 1, "bike_id_conflicts": 0}

    li = listings()
    assert set(li) == {"pd1", "pd2", "pd3", "pd4", "pd5"}
    for pid, listing in li.items():  # shop columns moved as they were
        o = old[pid]
        assert (listing.source, listing.raw_name, listing.details_link, listing.price,
                listing.first_seen_at, listing.last_seen_at) == \
            (SOURCE, o.raw_name, o.details_link, o.price, o.first_seen_at, o.last_seen_at)
        assert listing.fetched_at is None and listing.fetch_error is None

    ids = seeded["ids"]
    level = bike_by_norm("kross", "level 1")
    assert (level.id, level.company, level.status, level.bike_id) == (ids["pd1"], "KROSS", PENDING, None)
    wagant = bike_by_norm("romet", "wagant 3")
    assert (wagant.status, wagant.bike_id, wagant.attempts) == (DONE, seeded["wagant"], 1)
    orkan = bike_by_norm("romet", "orkan")
    assert (orkan.status, orkan.attempts, orkan.last_error) == (FAILED, 2, "ParseError: x")
    assert orkan.next_attempt_at is not None

    # pd3 (pending) + pd4 (done) → one bike: the done row survives with its casing and bike_id
    hexagon = bike_by_norm("kross", "hexagon 2")
    assert (hexagon.id, hexagon.company, hexagon.model, hexagon.status, hexagon.bike_id, hexagon.attempts) == \
        (ids["pd4"], "Kross", "hexagon 2", DONE, seeded["hexagon"], 2)
    assert li["pd3"].discovery_id == li["pd4"].discovery_id == ids["pd4"]
    assert hexagon.created_at == old["pd3"].first_seen_at  # the earliest first_seen_at of the group
    for pid in ("pd1", "pd2", "pd5"):
        assert li[pid].discovery_id == ids[pid]  # an unmerged row keeps its id


def test_new_layout_after_migration(seeded):
    mdl.migrate(verbose=False)
    assert not ({"source", "source_product_id", "raw_name", "details_link", "price", "first_seen_at",
                 "last_seen_at"} & columns("bike_discovery"))
    assert {"company_norm", "model_norm", "created_at"} <= columns("bike_discovery")
    insp = inspect(models.get_engine())
    assert not insp.has_table(mdl.OLD_TABLE)
    uniques = {uc["name"]: set(uc["column_names"]) for uc in insp.get_unique_constraints("bike_discovery_listing")}
    assert uniques["uq_bike_discovery_listing_source_product"] == {"source", "source_product_id"}
    uniques = {uc["name"]: set(uc["column_names"]) for uc in insp.get_unique_constraints("bike_discovery")}
    assert uniques == {"uq_bike_discovery_identity": {"company_norm", "model_norm"}}
    assert {i["name"] for i in insp.get_indexes("bike_discovery")} >= {mdl.STATUS_INDEX}
    fks = insp.get_foreign_keys("bike_discovery_listing")
    assert [fk["referred_table"] for fk in fks] == ["bike_discovery"]

    ensure_table()  # no longer refused
    bike_id = seeded["ids"]["pd1"]
    with session() as s:
        s.add(BikeDiscoveryListing(discovery_id=bike_id, source=SOURCE, source_product_id="pd1", raw_name="dup"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        s.add(BikeDiscovery(company=" kross", model="LEVEL 1"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_dry_run_writes_nothing(seeded):
    before = dump()
    result = mdl.migrate(dry_run=True, verbose=False)
    assert (result["status"], result["listings"], result["bikes"]) == (mdl.DRY_RUN, 5, 4)
    assert dump() == before
    assert "source" in columns("bike_discovery")


def test_second_run_is_a_no_op(seeded):
    mdl.migrate(verbose=False)
    before = dump()
    assert mdl.migrate(verbose=False) == {"status": mdl.ALREADY}
    assert mdl.migrate(dry_run=True, verbose=False) == {"status": mdl.ALREADY}
    assert dump() == before


def test_main_cli_reports_and_is_idempotent(seeded, capsys):
    url = str(models.get_engine().url)
    assert mdl.main(["--url", url, "--dry-run"]) == 0
    assert "dry run, rolled back" in capsys.readouterr().out
    assert "source" in columns("bike_discovery")
    assert mdl.main(["--url", url]) == 0
    assert "migrated: old_rows=5" in capsys.readouterr().out
    assert mdl.main(["--url", url]) == 0
    assert "already migrated" in capsys.readouterr().out


def test_main_refuses_remote_even_for_a_dry_run(old_layout_db):
    with pytest.raises(SystemExit, match="non-local"):
        mdl.main(["--url", "postgresql+psycopg://biker@127.0.0.1:6543/biker", "--dry-run"])


def test_missing_table_reported(old_layout_db):
    OLD_BIKE_DISCOVERY.drop(models.get_engine())
    assert mdl.migrate(verbose=False) == {"status": mdl.NO_TABLE}


def test_empty_old_table_migrates(old_layout_db):
    assert mdl.migrate(verbose=False)["status"] == mdl.MIGRATED
    assert not ({"source"} & columns("bike_discovery"))
    ensure_table()


def test_bike_id_taken_from_a_lower_ranked_row(old_layout_db):
    (bike_id,) = add_bikes(("Romet", "Orkan"))
    ids = old_layout_db(
        old_row("pd1", model="Orkan", status=PENDING, bike_id=bike_id),
        old_row("pd2", model="ORKAN", status=SKIPPED, last_error="HTTP 404: product gone"),
        old_row("pd3", model="orkan", status=IN_PROGRESS, attempts=1),
    )
    result = mdl.migrate(verbose=False)
    assert (result["bikes"], result["listings"], result["merged_rows"], result["bike_id_conflicts"]) == (1, 3, 2, 0)
    bike = bike_by_norm("romet", "orkan")
    assert (bike.id, bike.status, bike.bike_id, bike.last_error) == (ids[1], SKIPPED, bike_id, "HTTP 404: product gone")
    assert {li.discovery_id for li in listings().values()} == {ids[1]}


def test_status_ranking_and_bike_id_conflict(old_layout_db):
    a, b = add_bikes(("Romet", "Orkan"), ("ROMET", "ORKAN"))
    ids = old_layout_db(
        old_row("pd1", model="Orkan", status=FAILED, bike_id=a),
        old_row("pd2", model="Orkan", status=DONE, bike_id=b),
        old_row("pd3", model="Orkan", status=DONE),  # same rank as pd2, higher id → loses
    )
    result = mdl.migrate(verbose=False)
    assert result["bike_id_conflicts"] == 1
    bike = bike_by_norm("romet", "orkan")
    assert (bike.id, bike.status, bike.bike_id) == (ids[1], DONE, b)


def test_verify_failure_rolls_everything_back(seeded, monkeypatch):
    before = dump()

    def bad_verify(*args):
        raise mdl.MigrationError("boom")

    monkeypatch.setattr(mdl, "_verify", bad_verify)
    with pytest.raises(mdl.MigrationError):
        mdl.migrate(verbose=False)
    assert dump() == before
    assert mdl.main(["--url", str(models.get_engine().url)]) == 1


def test_listing_rows_next_to_old_layout_refused(seeded):
    engine = models.get_engine()
    BikeDiscoveryListing.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(BikeDiscoveryListing.__table__.insert().values(
            discovery_id=seeded["ids"]["pd1"], source=SOURCE, source_product_id="pdX", raw_name="x",
            first_seen_at=utcnow(), last_seen_at=utcnow(), updated_at=utcnow()))
    before = dump()
    with pytest.raises(mdl.MigrationError, match="already holds rows"):
        mdl.migrate(verbose=False)
    assert dump() == before


def test_empty_listing_table_next_to_old_layout_is_migrated(seeded):
    """An empty listing table left behind (e.g. by a create_all) must not keep a FK to the renamed old table."""
    BikeDiscoveryListing.__table__.create(models.get_engine())
    assert mdl.migrate(verbose=False)["status"] == mdl.MIGRATED
    assert len(listings()) == 5
    fks = inspect(models.get_engine()).get_foreign_keys("bike_discovery_listing")
    assert [fk["referred_table"] for fk in fks] == ["bike_discovery"]


def test_ensure_table_refuses_old_layout(old_layout_db):
    with pytest.raises(SystemExit, match="migrate_discovery_listings.py"):
        ensure_table()


def test_plan_is_pure_and_keeps_listing_order():
    now = utcnow().replace(tzinfo=None)
    rows = [{"id": i, "bike_id": None, "last_error": None, "locked_at": None, "next_attempt_at": None,
             **old_row(pid, model=m)} for i, pid, m in ((3, "pd3", "B"), (1, "pd1", "A"), (2, "pd2", " a "))]
    bikes, listings_, stats = mdl.plan(rows)
    assert [b["id"] for b in bikes] == [1, 3]
    assert [li["source_product_id"] for li in listings_] == ["pd1", "pd2", "pd3"]
    assert stats["survivor"] == {1: 1, 2: 1, 3: 3} and stats["merged_groups"] == 1
    assert all(li["first_seen_at"] < now for li in listings_)


def test_status_downgrade_fails_verification_and_rolls_back(seeded, monkeypatch):
    """A plan that would demote a survivor (done → pending) must not be committed."""
    before = dump()
    real_plan = mdl.plan

    def demoting_plan(rows):
        bikes, listings, stats = real_plan(rows)
        for bike in bikes:
            bike["status"] = PENDING
        return bikes, listings, stats

    monkeypatch.setattr(mdl, "plan", demoting_plan)
    with pytest.raises(mdl.MigrationError, match="lose their status"):
        mdl.migrate(verbose=False)
    assert dump() == before


def test_status_promotion_fails_the_per_status_counts(seeded, monkeypatch):
    """No row loses its status, but a pending bike turned done breaks the per-status counts."""
    before = dump()
    real_plan = mdl.plan

    def promoting_plan(rows):
        bikes, listings, stats = real_plan(rows)
        for bike in bikes:
            bike["status"] = DONE
        return bikes, listings, stats

    monkeypatch.setattr(mdl, "plan", promoting_plan)
    with pytest.raises(mdl.MigrationError, match="differ from the expected"):
        mdl.migrate(verbose=False)
    assert dump() == before


def test_rows_are_locked_before_they_are_read(seeded, monkeypatch):
    """Between the read and the rebuild no other connection may write the old table (it would be lost)."""
    import sqlite3

    path = models.get_engine().url.database
    real_plan, seen = mdl.plan, {}

    def plan_with_concurrent_write(rows):
        other = sqlite3.connect(path, timeout=0)
        try:
            other.execute("UPDATE bike_discovery SET attempts = attempts + 1")
            other.commit()
            seen["write"] = "committed"
        except sqlite3.OperationalError as exc:
            seen["write"] = str(exc)
        finally:
            other.close()
        return real_plan(rows)

    monkeypatch.setattr(mdl, "plan", plan_with_concurrent_write)
    assert mdl.migrate(verbose=False)["status"] == mdl.MIGRATED
    assert "locked" in seen["write"]
