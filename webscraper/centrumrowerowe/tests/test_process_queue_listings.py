"""process_queue.py walks a bike's listings (TODO-039): newest first, first page that parses wins."""
from datetime import timedelta

import process_queue as pq
from db import DONE, FAILED, SKIPPED, BikeDiscovery, BikeDiscoveryListing
from test_process_queue import URL, add_listing, add_row, claim_and_process, get_row, stub_parse

OLD_URL = "https://www.centrumrowerowe.pl/rower-old-pd1/"


def get_listing(pid):
    with pq.session() as s:
        listing = s.query(BikeDiscoveryListing).filter_by(source_product_id=pid).one()
        s.expunge(listing)
        return listing


def with_older_listing(row_id, pid="pd1", url=OLD_URL):
    with pq._tx() as s:
        add_listing(s, row_id, pid, url=url, seen_ago=timedelta(days=3))


def test_newest_listing_tried_first_and_wins(temp_db):
    row_id = add_row()
    with_older_listing(row_id)
    fetched = []
    assert claim_and_process(stub_parse(), fetch=lambda u: fetched.append(u) or (200, "")) == [DONE]
    assert fetched == [URL]
    newest, older = get_listing("pd27404"), get_listing("pd1")
    assert newest.fetched_at is not None and newest.fetch_error is None
    assert older.fetched_at is None


def test_failed_listing_falls_back_to_the_next(temp_db):
    row_id = add_row()
    with_older_listing(row_id)
    assert claim_and_process(stub_parse(), fetch=lambda u: (500, "") if u == URL else (200, "")) == [DONE]
    assert "HTTP 500" in get_listing("pd27404").fetch_error
    assert get_listing("pd1").fetch_error is None and get_listing("pd1").fetched_at is not None
    assert get_row(row_id).last_error is None


def test_every_listing_failed_fails_the_bike(temp_db):
    row_id = add_row()
    with_older_listing(row_id)
    assert claim_and_process(stub_parse(), fetch=lambda u: (404, "") if u == URL else (500, "")) == [FAILED]
    row = get_row(row_id)
    assert "pd27404: HTTP 404: product gone" in row.last_error and "pd1: FetchError: HTTP 500" in row.last_error
    assert row.next_attempt_at is not None


def test_every_listing_gone_skips_the_bike(temp_db):
    row_id = add_row()
    with_older_listing(row_id)
    assert claim_and_process(stub_parse(), fetch=lambda u: (410, "")) == [SKIPPED]
    row = get_row(row_id)
    assert row.bike_id is None and "HTTP 410" in row.last_error
    assert get_listing("pd1").fetch_error == "HTTP 410: product gone"


def test_bike_without_listings_fails_clearly(temp_db):
    with pq._tx() as s:
        bike = BikeDiscovery(company="Romet", model="Wagant 3")
        s.add(bike)
        s.flush()
        row_id = bike.id
    assert claim_and_process(stub_parse()) == [FAILED]
    assert get_row(row_id).last_error == pq.NO_LISTINGS


def test_listing_of_unknown_shop_fails_without_fetch(temp_db):
    row_id = add_row(source="other.pl")
    fetched = []
    assert claim_and_process(None, fetch=lambda u: fetched.append(u) or (200, "")) == [FAILED]
    assert fetched == [] and get_row(row_id).last_error.startswith("UnknownSource")


def test_corrected_name_colliding_with_another_bike_keeps_its_own(temp_db):
    add_row("pd9", model="Wagant 3 (2024)")  # parses to Romet / Wagant 3, like the row below
    other = add_row()
    ids = pq.claim_batch(10)
    assert [pq.process_row(i, fetch=lambda u: (200, ""), parse=stub_parse()) for i in ids] == [DONE, SKIPPED]
    first = get_row(ids[0])
    assert (first.company, first.model) == ("ROMET", "Wagant 3 (2024)")  # "romet / wagant 3" is taken
    assert (get_row(other).company, get_row(other).model) == ("Romet", "Wagant 3")
    assert first.bike_id == get_row(other).bike_id
