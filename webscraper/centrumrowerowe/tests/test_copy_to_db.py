"""copy_to_db.py between two temp SQLite files — never a real database."""
from datetime import timedelta

import pytest

import copy_to_db as ctd
from bike_store import DETAILS_ENDPOINT, tx
from app import cache
from app.schemas import BikeDetailsResponse
from db import DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, SOURCE, BikeDiscovery, ensure_table, models, repository, \
    session, utcnow
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


def details(brand, model, photo="https://src/a.jpg"):
    return StubParsed(brand, model).to_details_response(brand, model).model_copy(update={"photos": [photo]})


def add_bike(brand, model, photo="https://src/a.jpg", with_details=True):
    if with_details:
        repository.save_bike_details(brand, model, details(brand, model, photo))
    else:
        with tx() as s:
            s.add(models.Bike(brand=brand, model=model))
    with session() as s:
        return s.query(models.Bike).filter_by(brand=brand, model=model).one().id


def add_row(pid, status=PENDING, bike_id=None, **kw):
    with tx() as s:
        s.add(BikeDiscovery(source=SOURCE, source_product_id=pid, raw_name=f"Rower {pid}", company="ROMET",
                            model="Wagant 3", details_link=f"https://www.centrumrowerowe.pl/{pid}/",
                            status=status, bike_id=bike_id, **kw))


def rows():
    with session() as s:
        return {r.source_product_id: r for r in s.query(BikeDiscovery).all() if not s.expunge(r)}


def bikes():
    with session() as s:
        return [(b.brand, b.model) for b in s.query(models.Bike).order_by(models.Bike.id)]


def copy(urls, **kw):
    snap = ctd.read_source(urls["src"])
    return ctd.write_target(urls["tgt"], snap, **kw)


def seed_source(urls):
    use(urls["src"])
    bike_id = add_bike("Romet", "Wagant 3")
    add_row("pd1", DONE, bike_id, attempts=1)
    add_row("pd2", SKIPPED, last_error="HTTP 404: product gone", attempts=1)
    add_row("pd3")
    add_row("pd4", IN_PROGRESS, attempts=1, locked_at=utcnow())
    add_row("pd5", FAILED, attempts=2, last_error="ParseError: x", next_attempt_at=utcnow() + timedelta(hours=6))


def test_full_copy(dbs):
    seed_source(dbs)
    use(dbs["tgt"])
    add_bike("Kross", "Other")  # so target ids differ from source ids
    counts = copy(dbs)
    assert (counts["rows inserted"], counts["bikes written"], counts["cache written"], counts["bikes failed"]) == \
        (5, 1, 1, 0)
    use(dbs["tgt"])
    r = rows()
    assert bikes() == [("Kross", "Other"), ("Romet", "Wagant 3")]  # Romet is id 2 in the target, 1 in the source
    assert (r["pd1"].status, r["pd1"].bike_id, r["pd1"].company, r["pd1"].model) == (DONE, 2, "Romet", "Wagant 3")
    assert (r["pd2"].status, r["pd2"].bike_id, r["pd2"].last_error) == (SKIPPED, None, "HTTP 404: product gone")
    assert (r["pd3"].status, r["pd4"].status, r["pd4"].locked_at, r["pd4"].attempts) == (PENDING, PENDING, None, 0)
    assert (r["pd5"].status, r["pd5"].attempts, r["pd5"].last_error) == (FAILED, 2, "ParseError: x")
    assert repository.get_bike_details("Romet", "Wagant 3").photos == ["https://src/a.jpg"]
    hit = cache.get_cached(DETAILS_ENDPOINT, {"company": "Romet", "model": "Wagant 3"}, BikeDetailsResponse)
    assert hit is not None and hit.company == "Romet"


def test_second_run_changes_nothing(dbs):
    seed_source(dbs)
    copy(dbs)
    use(dbs["tgt"])
    before = (bikes(), {k: (v.status, v.bike_id, v.updated_at) for k, v in rows().items()})
    counts = copy(dbs)
    assert (counts["rows inserted"], counts["rows updated"], counts["rows unchanged"]) == (0, 0, 5)
    assert (counts["bikes written"], counts["bikes kept"], counts["cache written"], counts["cache present"]) == \
        (0, 1, 0, 1)
    use(dbs["tgt"])
    assert (bikes(), {k: (v.status, v.bike_id, v.updated_at) for k, v in rows().items()}) == before


def test_target_fresh_details_under_other_casing_are_kept(dbs):
    seed_source(dbs)
    use(dbs["tgt"])
    add_bike("ROMET", "WAGANT 3", photo="https://tgt/own.jpg")
    counts = copy(dbs)
    assert (counts["bikes kept"], counts["bikes written"]) == (1, 0)
    use(dbs["tgt"])
    assert bikes() == [("ROMET", "WAGANT 3")]
    assert repository.get_bike_details("ROMET", "WAGANT 3").photos == ["https://tgt/own.jpg"]
    r = rows()["pd1"]
    assert (r.status, r.bike_id, r.company, r.model) == (DONE, 1, "ROMET", "WAGANT 3")


def test_target_bike_without_details_filled_under_target_casing(dbs):
    seed_source(dbs)
    use(dbs["tgt"])
    add_bike("romet", "wagant 3", with_details=False)
    counts = copy(dbs)
    assert counts["bikes written"] == 1
    use(dbs["tgt"])
    assert bikes() == [("romet", "wagant 3")]
    got = repository.get_bike_details("romet", "wagant 3")
    assert (got.company, got.model, got.photos) == ("romet", "wagant 3", ["https://src/a.jpg"])


def test_target_done_row_not_downgraded_pending_promoted(dbs):
    use(dbs["src"])
    bike_id = add_bike("Romet", "Wagant 3")
    add_row("pd1")  # pending in the source
    add_row("pd2", DONE, bike_id)
    use(dbs["tgt"])
    other = add_bike("Kross", "Other")
    add_row("pd1", DONE, other)
    add_row("pd2", FAILED, attempts=3, last_error="old")
    counts = copy(dbs)
    assert (counts["rows unchanged"], counts["rows updated"]) == (1, 1)
    use(dbs["tgt"])
    r = rows()
    assert (r["pd1"].status, r["pd1"].bike_id) == (DONE, other)
    assert (r["pd2"].status, r["pd2"].bike_id, r["pd2"].next_attempt_at) == (DONE, 2, None)


def test_failed_bike_write_copies_row_as_pending(dbs, monkeypatch):
    seed_source(dbs)
    monkeypatch.setattr(repository, "save_bike_details", lambda *a, **k: None)  # swallowed failure
    counts = copy(dbs)
    assert (counts["bikes failed"], counts["rows inserted"]) == (1, 5)
    use(dbs["tgt"])
    r = rows()["pd1"]
    assert (r.status, r.bike_id, r.attempts) == (PENDING, None, 0)


def test_source_details_stale_row_copied_as_pending(dbs):
    seed_source(dbs)
    use(dbs["src"])
    with tx() as s:
        s.query(models.BikeDetails).update({models.BikeDetails.updated_at: utcnow() - timedelta(days=31)})
    counts = copy(dbs)
    assert counts["bikes written"] == 0
    use(dbs["tgt"])
    assert rows()["pd1"].status == PENDING and bikes() == []


def test_dry_run_writes_nothing(dbs):
    seed_source(dbs)
    counts = copy(dbs, dry_run=True)
    assert (counts["rows inserted"], counts["bikes written"], counts["cache written"]) == (5, 1, 1)
    use(dbs["tgt"])
    assert rows() == {} and bikes() == []
    assert cache.get_cached(DETAILS_ENDPOINT, {"company": "Romet", "model": "Wagant 3"}, BikeDetailsResponse) is None


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
