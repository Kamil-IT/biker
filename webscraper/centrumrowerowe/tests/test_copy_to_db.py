"""copy_to_db.py between two temp SQLite files — never a real database."""
from datetime import timedelta

import pytest

import copy_to_db as ctd
from bike_store import tx
from app import photos_repository
from db import DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, SOURCE, BikeDiscovery, BikeDiscoveryListing, ensure_table, \
    models, repository, session, utcnow
from test_process_queue import StubParsed


@pytest.fixture
def dbs(tmp_path):
    prev = models._db_url
    urls = {name: f"sqlite:///{tmp_path / (name + '.db')}" for name in ("src", "tgt")}
    for url in urls.values():
        models.configure_db(url)
        models.init_db()
        ensure_table()
    yield urls
    models.dispose_engine()
    models._db_url = prev


def use(url):
    models.configure_db(url)


def add_bike(brand, model, photo="https://src/a.jpg", with_details=True):
    if with_details:
        repository.save_bike_details(brand, model, StubParsed(brand, model).to_details_response(brand, model))
    else:
        with tx() as s:
            s.add(models.Bike(brand=brand, model=model))
    if photo:
        photos_repository.save_bike_photos(brand, model, [photo])
    with session() as s:
        return s.query(models.Bike).filter_by(brand=brand, model=model).one().id


def photos(brand, model):
    return photos_repository.get_bike_photos(brand, model).photos


def add_row(pid, status=PENDING, bike_id=None, model=None, **kw):
    """A queue row (bike identity ROMET / `model`, default one per pid) with the single listing `pid`."""
    with tx() as s:
        row = BikeDiscovery(company="ROMET", model=model or f"Model {pid}", status=status, bike_id=bike_id, **kw)
        s.add(row)
        s.flush()
        s.add(BikeDiscoveryListing(discovery_id=row.id, source=SOURCE, source_product_id=pid, raw_name=f"Rower {pid}",
                                   details_link=f"https://www.centrumrowerowe.pl/{pid}/"))


def rows():
    """listing pid → its bike_discovery row, in the current database."""
    with session() as s:
        pairs = s.query(BikeDiscoveryListing.source_product_id, BikeDiscovery).join(
            BikeDiscovery, BikeDiscovery.id == BikeDiscoveryListing.discovery_id).all()
        for _, row in pairs:
            s.expunge(row)
        return dict(pairs)


def bikes():
    with session() as s:
        return [(b.brand, b.model) for b in s.query(models.Bike).order_by(models.Bike.id)]


def copy(urls, **kw):
    snap = ctd.read_source(urls["src"])
    return ctd.write_target(urls["tgt"], snap, **kw)


def seed_source(urls):
    use(urls["src"])
    bike_id = add_bike("Romet", "Wagant 3")
    add_row("pd1", DONE, bike_id, model="Wagant 3", attempts=1)
    add_row("pd2", SKIPPED, last_error="HTTP 404: product gone", attempts=1)
    add_row("pd3")
    add_row("pd4", IN_PROGRESS, attempts=1, locked_at=utcnow())
    add_row("pd5", FAILED, attempts=2, last_error="ParseError: x", next_attempt_at=utcnow() + timedelta(hours=6))


def test_full_copy(dbs):
    seed_source(dbs)
    use(dbs["tgt"])
    add_bike("Kross", "Other")  # so target ids differ from source ids
    counts = copy(dbs)
    assert (counts["rows inserted"], counts["bikes written"], counts["bikes failed"]) == \
        (5, 1, 0)
    assert (counts["listings inserted"], counts["listings unchanged"]) == (5, 0)
    use(dbs["tgt"])
    r = rows()
    assert bikes() == [("Kross", "Other"), ("Romet", "Wagant 3")]  # Romet is id 2 in the target, 1 in the source
    assert (r["pd1"].status, r["pd1"].bike_id, r["pd1"].company, r["pd1"].model) == (DONE, 2, "Romet", "Wagant 3")
    assert (r["pd2"].status, r["pd2"].bike_id, r["pd2"].last_error) == (SKIPPED, None, "HTTP 404: product gone")
    assert (r["pd3"].status, r["pd4"].status, r["pd4"].locked_at, r["pd4"].attempts) == (PENDING, PENDING, None, 0)
    assert (r["pd5"].status, r["pd5"].attempts, r["pd5"].last_error) == (FAILED, 2, "ParseError: x")
    assert repository.get_bike_details("Romet", "Wagant 3") is not None
    assert photos("Romet", "Wagant 3") == ["https://src/a.jpg"] and counts["photos written"] == 1


def test_second_run_changes_nothing(dbs):
    seed_source(dbs)
    copy(dbs)
    use(dbs["tgt"])
    before = (bikes(), {k: (v.status, v.bike_id, v.updated_at) for k, v in rows().items()})
    counts = copy(dbs)
    assert (counts["rows inserted"], counts["rows updated"], counts["rows unchanged"]) == (0, 0, 5)
    assert (counts["listings inserted"], counts["listings unchanged"]) == (0, 5)
    assert (counts["bikes written"], counts["bikes kept"],
            counts["photos written"], counts["photos present"]) == (0, 1, 0, 1)
    use(dbs["tgt"])
    assert (bikes(), {k: (v.status, v.bike_id, v.updated_at) for k, v in rows().items()}) == before


def test_target_details_and_photos_under_other_casing_are_kept(dbs):
    seed_source(dbs)
    use(dbs["tgt"])
    add_bike("ROMET", "WAGANT 3", photo="https://tgt/own.jpg")
    counts = copy(dbs)
    assert (counts["bikes kept"], counts["bikes written"]) == (1, 0)
    use(dbs["tgt"])
    assert bikes() == [("ROMET", "WAGANT 3")]
    assert photos("ROMET", "WAGANT 3") == ["https://tgt/own.jpg"] and counts["photos present"] == 1
    r = rows()["pd1"]
    assert (r.status, r.bike_id, r.company, r.model) == (DONE, 1, "ROMET", "WAGANT 3")


def test_target_bike_without_details_filled_under_target_casing(dbs):
    seed_source(dbs)
    use(dbs["tgt"])
    add_bike("romet", "wagant 3", photo=None, with_details=False)
    counts = copy(dbs)
    assert counts["bikes written"] == 1
    use(dbs["tgt"])
    assert bikes() == [("romet", "wagant 3")]
    got = repository.get_bike_details("romet", "wagant 3")
    assert (got.company, got.model) == ("romet", "wagant 3")
    assert photos("romet", "wagant 3") == ["https://src/a.jpg"]


def test_target_details_without_photos_get_the_source_photos(dbs):
    seed_source(dbs)
    use(dbs["tgt"])
    add_bike("Romet", "Wagant 3", photo=None)
    counts = copy(dbs)
    assert (counts["bikes kept"], counts["photos written"]) == (1, 1)
    use(dbs["tgt"])
    assert photos("Romet", "Wagant 3") == ["https://src/a.jpg"]


def test_target_photos_without_details_are_kept(dbs):
    seed_source(dbs)
    use(dbs["tgt"])
    add_bike("Romet", "Wagant 3", photo="https://searcher/1.jpg", with_details=False)
    counts = copy(dbs)
    assert (counts["bikes written"], counts["photos present"]) == (1, 1)
    use(dbs["tgt"])
    assert photos("Romet", "Wagant 3") == ["https://searcher/1.jpg"]


def test_target_done_row_not_downgraded_pending_promoted(dbs):
    use(dbs["src"])
    bike_id = add_bike("Romet", "Wagant 3")
    add_row("pd1")  # pending in the source
    add_row("pd2", DONE, bike_id, model="Wagant 3")
    use(dbs["tgt"])
    other = add_bike("Kross", "Other")
    add_row("pd1", DONE, other)
    add_row("pd2", FAILED, model="WAGANT 3", attempts=3, last_error="old")  # same identity, other casing
    counts = copy(dbs)
    assert (counts["rows unchanged"], counts["rows updated"]) == (1, 1)
    use(dbs["tgt"])
    r = rows()
    assert (r["pd1"].status, r["pd1"].bike_id) == (DONE, other)
    assert (r["pd2"].status, r["pd2"].bike_id, r["pd2"].next_attempt_at) == (DONE, 2, None)


def test_failed_bike_write_copies_row_as_pending(dbs, monkeypatch):
    seed_source(dbs)
    monkeypatch.setattr(repository, "save_bike_details", lambda *a, **k: False)  # swallowed failure
    counts = copy(dbs)
    assert (counts["bikes failed"], counts["rows inserted"]) == (1, 5)
    use(dbs["tgt"])
    r = rows()["pd1"]
    assert (r.status, r.bike_id, r.attempts) == (PENDING, None, 0)


def test_old_source_details_are_copied_no_ttl(dbs):
    seed_source(dbs)
    use(dbs["src"])
    with tx() as s:
        s.query(models.Bike).update({models.Bike.updated_at: utcnow() - timedelta(days=400)})
    assert copy(dbs)["bikes written"] == 1


def test_source_bike_without_details_row_copied_as_pending(dbs):
    use(dbs["src"])
    bike_id = add_bike("Romet", "Wagant 3", with_details=False)
    add_row("pd1", DONE, bike_id)
    counts = copy(dbs)
    assert counts["bikes written"] == 0
    use(dbs["tgt"])
    assert rows()["pd1"].status == PENDING and bikes() == []


def test_dry_run_writes_nothing(dbs):
    seed_source(dbs)
    counts = copy(dbs, dry_run=True)
    assert (counts["rows inserted"], counts["bikes written"], counts["photos written"]) == \
        (5, 1, 1)
    use(dbs["tgt"])
    assert rows() == {} and bikes() == []
    with session() as s:
        assert s.query(models.BikeDetailPhoto).count() == 0


def test_main_copies_and_dry_run(dbs, capsys):
    seed_source(dbs)
    args = ["--source-url", dbs["src"], "--target-url", dbs["tgt"]]
    assert ctd.main(args + ["--dry-run"]) == 0
    assert "dry run, would be: rows_inserted=5" in capsys.readouterr().out
    assert ctd.main(args) == 0
    out = capsys.readouterr().out
    assert "source: sqlite" in out and "target: sqlite" in out and "rows_inserted=5" in out


def test_same_database_refused(dbs, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="same database"):
        ctd.main(["--source-url", dbs["src"], "--target-url", "sqlite:///src.db"])
    assert ctd.database_identity("postgresql+psycopg://a@localhost/biker") == \
        ctd.database_identity("postgresql+psycopg://b:pw@127.0.0.1:5432/biker")


@pytest.mark.parametrize("target", [
    "postgresql+psycopg://biker@db.example.com:5432/biker",
    "postgresql+psycopg://biker@127.0.0.1:6543/biker",  # the Cloud SQL proxy port
])
def test_remote_target_refused_without_allow_remote(dbs, target):
    with pytest.raises(SystemExit, match="non-local"):
        ctd.main(["--source-url", dbs["src"], "--target-url", target])
