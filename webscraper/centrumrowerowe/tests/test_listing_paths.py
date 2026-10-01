"""Listing-path edge cases (TODO-039) not covered elsewhere: multi-shop bikes, dry run, store errors, copy."""
from datetime import timedelta

import copy_to_db as ctd
import process_queue as pq
from bike_store import tx
from db import (
    DONE, FAILED, PENDING, SOURCE, BikeDiscovery, BikeDiscoveryListing, models, repository, session,
)
from test_copy_to_db import add_bike, add_row as copy_add_row, copy, dbs, rows, use  # noqa: F401  (dbs: fixture)
from test_process_queue import URL, add_listing, add_row, bike_rows, get_row, stub_parse

OTHER = "other.pl"
OTHER_URL = "https://www.other.pl/rower-1/"
OLD_URL = "https://www.centrumrowerowe.pl/rower-old-pd2/"


def listing(pid):
    with session() as s:
        li = s.query(BikeDiscoveryListing).filter_by(source_product_id=pid).one()
        s.expunge(li)
        return li


def multi_shop_bike(model="Wagant 3"):
    """A bike listed by centrumrowerowe.pl (pd1, a day old) and by another shop (o1, newest)."""
    with pq._tx() as s:
        bike = BikeDiscovery(company="ROMET", model=model)
        s.add(bike)
        s.flush()
        add_listing(s, bike.id, "pd1", url=URL, seen_ago=timedelta(days=1))
        add_listing(s, bike.id, "o1", source=OTHER, url=OTHER_URL)
        return bike.id


def test_source_filter_claims_a_multi_shop_bike_other_shop_listing_recorded(temp_db, monkeypatch):
    row_id = multi_shop_bike()
    only_other = add_row("o2", source=OTHER, url=OTHER_URL + "2")
    monkeypatch.setitem(pq.PARSERS, SOURCE, stub_parse())
    assert pq.claim_batch(10, SOURCE) == [row_id]  # the bike listed only by the other shop is not claimed
    fetched = []
    assert pq.process_row(row_id, fetch=lambda u: fetched.append(u) or (200, "")) == DONE
    assert fetched == [URL]  # the other shop has no parser: never fetched
    assert listing("o1").fetch_error.startswith("UnknownSource") and listing("o1").fetched_at is not None
    assert listing("pd1").fetch_error is None
    assert get_row(row_id).last_error is None
    assert get_row(only_other).status == PENDING


def test_store_error_fails_at_once_without_trying_the_next_listing(temp_db, monkeypatch):
    row_id = add_row()  # pd27404, newest
    with pq._tx() as s:
        add_listing(s, row_id, "pd2", url=OLD_URL, seen_ago=timedelta(days=3))
    with pq._tx() as s:
        s.add(models.Bike(brand="Romet", model="Wagant 3"))
    monkeypatch.setattr(repository, "save_bike_details", lambda *a, **k: False)  # swallowed save failure
    fetched = []
    ids = pq.claim_batch(10)
    assert [pq.process_row(i, fetch=lambda u: fetched.append(u) or (200, ""), parse=stub_parse()) for i in ids] \
        == [FAILED]
    assert fetched == [URL]
    assert "save_bike_details stored nothing" in get_row(row_id).last_error
    assert listing("pd2").fetched_at is None


def test_retry_after_all_listings_failed_clears_listing_errors(temp_db):
    row_id = add_row()
    with pq._tx() as s:
        add_listing(s, row_id, "pd2", url=OLD_URL, seen_ago=timedelta(days=3))
    assert [pq.process_row(i, fetch=lambda u: (500, ""), parse=stub_parse()) for i in pq.claim_batch(10)] == [FAILED]
    assert listing("pd2").fetch_error and listing("pd27404").fetch_error
    assert pq.requeue_failed(None) == 1
    assert [pq.process_row(i, fetch=lambda u: (200, ""), parse=stub_parse()) for i in pq.claim_batch(10)] == [DONE]
    assert listing("pd27404").fetch_error is None  # newest parsed; the older one keeps its last error
    assert get_row(row_id).status == DONE


def test_dry_run_walks_listings_until_one_parses(temp_db, capsys):
    row_id = add_row()
    with pq._tx() as s:
        add_listing(s, row_id, "pd2", url=OLD_URL, seen_ago=timedelta(days=3))
        add_listing(s, row_id, "pd3", url=OLD_URL + "3", seen_ago=timedelta(days=5))
    fetched = []

    def fetch(url):
        fetched.append(url)
        return (500, "") if url == URL else (200, "")

    assert pq.dry_run(10, None, False, 0, fetch=fetch, parse=stub_parse()) == 1
    out = capsys.readouterr().out
    assert fetched == [URL, OLD_URL]  # stops at the first page that parses
    assert "pd27404: ERROR" in out and "pd2: 'Romet' 'Wagant 3'" in out and "pd3" not in out
    row = get_row(row_id)
    assert (row.status, row.attempts) == (PENDING, 0) and bike_rows() == []
    assert listing("pd27404").fetched_at is None  # a dry run records nothing on the listings


def test_dry_run_bike_without_listings(temp_db, capsys):
    with pq._tx() as s:
        s.add(BikeDiscovery(company="Romet", model="Orkan"))
    assert pq.dry_run(10, None, False, 0, fetch=lambda u: (200, ""), parse=stub_parse()) == 1
    assert pq.NO_LISTINGS in capsys.readouterr().out


# ── copy_to_db with several listings ──

def add_other_listing(pid, model):
    with tx() as s:
        bike = s.query(BikeDiscovery).filter_by(model_norm=model.lower()).one()
        s.add(BikeDiscoveryListing(discovery_id=bike.id, source=OTHER, source_product_id=pid, raw_name=pid,
                                   details_link=OTHER_URL))


def listings_by_pid():
    with session() as s:
        return {li.source_product_id: (li.source, li.discovery_id) for li in s.query(BikeDiscoveryListing)}


def test_copy_multi_shop_bike_copies_every_listing(dbs):
    use(dbs["src"])
    copy_add_row("pd1", model="Wagant 3")
    add_other_listing("o1", "Wagant 3")
    counts = copy(dbs)
    assert (counts["rows inserted"], counts["listings inserted"]) == (1, 2)
    use(dbs["tgt"])
    got = listings_by_pid()
    assert set(got) == {"pd1", "o1"} and got["pd1"][1] == got["o1"][1]
    assert copy(dbs)["listings unchanged"] == 2


def test_copy_source_filter_keeps_only_that_shops_listings(dbs):
    use(dbs["src"])
    copy_add_row("pd1", model="Wagant 3")
    add_other_listing("o1", "Wagant 3")
    copy_add_row("pd2", model="Orkan")
    with tx() as s:  # a bike listed only by the other shop
        bike = BikeDiscovery(company="ROMET", model="Only Other")
        s.add(bike)
        s.flush()
        s.add(BikeDiscoveryListing(discovery_id=bike.id, source=OTHER, source_product_id="o2", raw_name="o2"))
    snap = ctd.read_source(dbs["src"], shop=OTHER)
    assert sorted(r["model"] for r in snap.rows) == ["Only Other", "Wagant 3"]
    assert sorted(li["source_product_id"] for r in snap.rows for li in r["listings"]) == ["o1", "o2"]
    counts = ctd.write_target(dbs["tgt"], snap)
    assert (counts["rows inserted"], counts["listings inserted"]) == (2, 2)
    use(dbs["tgt"])
    assert set(listings_by_pid()) == {"o1", "o2"}


def test_copy_never_reparents_a_target_listing(dbs):
    """The target already has pd1 on another bike: it stays there, the source bike arrives without it."""
    use(dbs["tgt"])
    copy_add_row("pd1", model="Target Bike")
    use(dbs["src"])
    copy_add_row("pd1", model="Wagant 3")
    copy_add_row("pd2", model="Orkan")
    counts = copy(dbs)
    assert (counts["rows inserted"], counts["listings inserted"], counts["listings unchanged"]) == (2, 1, 1)
    use(dbs["tgt"])
    r = rows()
    assert r["pd1"].model == "Target Bike"
    with session() as s:
        wagant = s.query(BikeDiscovery).filter_by(model_norm="wagant 3").one()
        assert s.query(BikeDiscoveryListing).filter_by(discovery_id=wagant.id).count() == 0


def test_copy_promotes_a_pending_target_bike_and_adds_the_new_listing(dbs):
    """Same identity in both, different listings: the target row is promoted, its listing kept, the source's added."""
    use(dbs["src"])
    bike_id = add_bike("Romet", "Wagant 3")
    copy_add_row("pd1", DONE, bike_id, model="Wagant 3", attempts=1)
    use(dbs["tgt"])
    copy_add_row("pd9", model="Wagant 3")
    counts = copy(dbs)
    assert (counts["rows updated"], counts["listings inserted"]) == (1, 1)
    use(dbs["tgt"])
    got = listings_by_pid()
    assert got["pd1"][1] == got["pd9"][1]
    with session() as s:
        bike = s.get(BikeDiscovery, got["pd9"][1])
        assert bike.status == DONE and bike.bike_id is not None and s.query(BikeDiscovery).count() == 1
