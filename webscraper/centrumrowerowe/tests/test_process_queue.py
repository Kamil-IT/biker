"""process_queue.py on a temp SQLite database (the `temp_db` fixture) with a fake fetch."""
from datetime import timedelta
from pathlib import Path

import pytest

import process_queue as pq
from db import DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, SOURCE, BikeDiscovery, models, repository, utcnow
from app import photos_repository
from app.schemas import (
    BikeCategory, BikeDescription, BikeDetailsResponse, BikeSubcategory, ComponentElement, SpecItem,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "https://www.centrumrowerowe.pl/rower-trekkingowy-romet-wagant-3-pd27404/"


class StubParsed:
    """Stands in for product_parser.ParsedBike so these tests do not depend on the real parser."""

    def __init__(self, brand="Romet", model="Wagant 3"):
        self.brand, self.model, self.raw_name = brand, model, f"Rower trekkingowy {brand} {model}"
        self.bike_type, self.is_electric, self.frame_sizes = "trekkingowy", False, ["17\"", "19\""]
        self.photos = ["https://example.com/a.jpg", "https://example.com/b.jpg"]
        self.components = [BikeCategory(category="Wheels", subcategories=[BikeSubcategory(
            subcategory="Wheels", elements=[ComponentElement(
                name="Wheels", description="", specs=[SpecItem(key="Wheel size", value="28\"")])])])]

    def to_details_response(self, company, model):
        return BikeDetailsResponse(
            company=company,
            model=model,
            description=BikeDescription(text="Rower trekkingowy.", segments=[], citations=[]),
            components=self.components,
        )  # photos are not part of details any more — process_row stores self.photos itself


def stored_photos(brand, model):
    return photos_repository.get_bike_photos(brand, model).photos


def add_photos(brand, model, urls):
    assert photos_repository.save_bike_photos(brand, model, urls) == len(urls)


def stub_parse(brand="Romet", model="Wagant 3"):
    return lambda html, url: StubParsed(brand, model)


def fetch_ok(url):
    return 200, "<html></html>"


def add_row(pid="pd27404", **kw):
    with pq._tx() as s:
        row = BikeDiscovery(source=SOURCE, source_product_id=pid, raw_name="Rower trekkingowy ROMET Wagant 3",
                            company="ROMET", model="Wagant 3", details_link=URL, **kw)
        s.add(row)
        s.flush()
        return row.id


def get_row(row_id):
    with pq.session() as s:
        row = s.get(BikeDiscovery, row_id)
        s.expunge(row)
        return row


def bike_rows():
    with pq.session() as s:
        return [(b.id, b.brand, b.model) for b in s.query(models.Bike).order_by(models.Bike.id)]


def claim_and_process(parse, fetch=fetch_ok):
    ids = pq.claim_batch(10)
    return [pq.process_row(i, fetch=fetch, parse=parse) for i in ids]


def test_backoff():
    assert [pq.backoff_for(n) for n in (1, 2, 3, 4)] == [
        timedelta(hours=1), timedelta(hours=6), timedelta(hours=24), timedelta(hours=24)]


def test_happy_path_stores_details(temp_db):
    row_id = add_row()
    assert claim_and_process(stub_parse()) == [DONE]
    row = get_row(row_id)
    assert (row.status, row.attempts, row.last_error, row.locked_at) == (DONE, 1, None, None)
    assert (row.company, row.model) == ("Romet", "Wagant 3")
    assert bike_rows() == [(row.bike_id, "Romet", "Wagant 3")]
    details = repository.get_bike_details("Romet", "Wagant 3")
    # the details view's gallery reads POST /v1/bike/photos → photos_repository.get_bike_photos
    assert stored_photos("ROMET", "wagant 3") == ["https://example.com/a.jpg", "https://example.com/b.jpg"]
    assert details.components[0].subcategories[0].elements[0].specs[0].value == '28"'
    with pq.session() as s:
        assert s.query(models.BikeDetailPhoto).count() == 2
        assert s.query(models.BikeDetailComponent).count() == 1


REAL_PAGES = [
    ("trekking_romet_wagant_3.html", "Romet", "Wagant 3", False),
    ("mtb_focus_whistler_3_6.html", "Focus", "Whistler 3.6", False),
    ("ebike_haibike_trekking_3_high.html", "Haibike", "Trekking 3 High", True),
    ("ebike_le_grand_elille_3.html", "Le Grand", "eLille 3", True),
]


@pytest.mark.parametrize("fixture,brand,model,electric", REAL_PAGES)
def test_real_parser_on_fixture(temp_db, fixture, brand, model, electric):
    pytest.importorskip("product_parser")
    html = (FIXTURES / fixture).read_text(encoding="utf-8")
    row_id = add_row()
    assert claim_and_process(None, fetch=lambda url: (200, html)) == [DONE]
    row = get_row(row_id)
    assert (row.company, row.model) == (brand, model)
    details = repository.get_bike_details(brand, model)
    assert details is not None and details.description.text and details.components
    assert stored_photos(brand, model)
    categories = {c.category for c in details.components}
    assert ("Electric / Powertrain" in categories) is electric
    assert len(bike_rows()) == 1


def test_real_parser_error_fails(temp_db):
    pytest.importorskip("product_parser")
    row_id = add_row()
    assert claim_and_process(None, fetch=lambda url: (200, "<html><body>nothing</body></html>")) == [FAILED]
    assert get_row(row_id).last_error.startswith("ParseError")


def test_existing_details_and_photos_skipped_unchanged(temp_db):
    repository.save_bike_details("Romet", "Wagant 3", StubParsed().to_details_response("Romet", "Wagant 3"))
    add_photos("Romet", "Wagant 3", ["https://x/orig.jpg"])
    before = repository.get_bike_details("Romet", "Wagant 3")
    row_id = add_row()
    assert claim_and_process(stub_parse("ROMET", "WAGANT 3")) == [SKIPPED]
    row = get_row(row_id)
    assert row.status == SKIPPED and row.bike_id == bike_rows()[0][0]
    assert (row.company, row.model) == ("Romet", "Wagant 3")
    assert len(bike_rows()) == 1
    assert repository.get_bike_details("Romet", "Wagant 3") == before
    assert stored_photos("Romet", "Wagant 3") == ["https://x/orig.jpg"]  # never replaced


def test_existing_details_without_photos_get_the_shop_photos(temp_db):
    repository.save_bike_details("Romet", "Wagant 3", StubParsed().to_details_response("Romet", "Wagant 3"))
    before = repository.get_bike_details("Romet", "Wagant 3")
    add_row()
    assert claim_and_process(stub_parse()) == [SKIPPED]
    assert repository.get_bike_details("Romet", "Wagant 3") == before
    assert stored_photos("Romet", "Wagant 3") == ["https://example.com/a.jpg", "https://example.com/b.jpg"]


def test_existing_bike_without_details_filled_with_stored_casing(temp_db):
    with pq._tx() as s:
        s.add(models.Bike(brand="Romet", model="Wagant 3"))
    row_id = add_row()
    assert claim_and_process(stub_parse("ROMET", "wagant 3")) == [DONE]
    assert len(bike_rows()) == 1
    row = get_row(row_id)
    assert (row.company, row.model, row.bike_id) == ("Romet", "Wagant 3", bike_rows()[0][0])
    assert repository.get_bike_details("Romet", "Wagant 3") is not None
    assert len(stored_photos("Romet", "Wagant 3")) == 2


def test_photos_of_a_bike_without_details_are_kept(temp_db):
    with pq._tx() as s:
        s.add(models.Bike(brand="Romet", model="Wagant 3"))
    add_photos("Romet", "Wagant 3", ["https://searcher/1.jpg"])  # e.g. from the photo searcher
    add_row()
    assert claim_and_process(stub_parse()) == [DONE]
    assert stored_photos("Romet", "Wagant 3") == ["https://searcher/1.jpg"]


def test_old_details_are_kept_no_ttl(temp_db):
    repository.save_bike_details("Romet", "Wagant 3", StubParsed().to_details_response("Romet", "Wagant 3"))
    with pq._tx() as s:
        s.query(models.BikeDetails).update({models.BikeDetails.updated_at: utcnow() - timedelta(days=400)})
    add_row()
    assert claim_and_process(stub_parse()) == [SKIPPED]
    assert len(bike_rows()) == 1


def test_page_without_photos_still_done(temp_db):
    parsed = StubParsed()
    parsed.photos = []
    add_row()
    assert claim_and_process(lambda html, url: parsed) == [DONE]
    assert stored_photos("Romet", "Wagant 3") == []


def test_photo_write_failure_leaves_row_done(temp_db, monkeypatch):
    monkeypatch.setattr(photos_repository, "save_bike_photos", lambda *a, **k: 0)  # swallowed failure
    row_id = add_row()
    assert claim_and_process(stub_parse()) == [DONE]
    assert get_row(row_id).last_error is None
    assert repository.get_bike_details("Romet", "Wagant 3") is not None
    assert stored_photos("Romet", "Wagant 3") == []


@pytest.mark.parametrize("status", [404, 410])
def test_gone_page_skipped(temp_db, status):
    row_id = add_row()
    assert claim_and_process(stub_parse(), fetch=lambda url: (status, "")) == [SKIPPED]
    row = get_row(row_id)
    assert row.status == SKIPPED and row.bike_id is None and bike_rows() == []


def boom(html, url):
    raise ValueError("no JSON-LD Product")


def test_parse_error_fails_with_backoff(temp_db):
    row_id = add_row()
    start = utcnow()
    assert claim_and_process(boom) == [FAILED]
    row = get_row(row_id)
    assert (row.status, row.attempts, row.locked_at) == (FAILED, 1, None)
    assert row.last_error.startswith("ValueError: no JSON-LD Product")
    wait = pq._aware(row.next_attempt_at) - start
    assert timedelta(minutes=59) < wait < timedelta(minutes=61)
    assert pq.claim_batch(10) == []  # not due yet


def test_long_error_truncated_and_http_500_fails(temp_db):
    row_id = add_row()
    assert claim_and_process(lambda h, u: (_ for _ in ()).throw(RuntimeError("x" * 5000))) == [FAILED]
    assert len(get_row(row_id).last_error) == 1000
    row2 = add_row("pd2")
    assert claim_and_process(stub_parse(), fetch=lambda url: (500, "")) == [FAILED]
    assert "HTTP 500" in get_row(row2).last_error


def test_third_failure_is_final(temp_db):
    row_id = add_row()
    for attempt in (1, 2, 3):
        with pq._tx() as s:  # make the backoff due
            s.get(BikeDiscovery, row_id).next_attempt_at = utcnow() - timedelta(seconds=1)
        assert claim_and_process(boom) == [FAILED]
        assert get_row(row_id).attempts == attempt
    with pq._tx() as s:
        s.get(BikeDiscovery, row_id).next_attempt_at = utcnow() - timedelta(days=2)
    assert pq.claim_batch(10) == []
    assert get_row(row_id).status == FAILED
    assert pq.requeue_failed(None) == 1  # --retry-failed brings it back
    assert pq.claim_batch(10) == [row_id]


def test_one_bad_row_does_not_stop_batch(temp_db):
    add_row("pd1")
    add_row("pd2")

    def fetch(url, calls=[]):
        calls.append(url)
        return (200, "bad") if len(calls) == 1 else (200, "good")

    def parse(html, url):
        if html == "bad":
            raise ValueError("bad page")
        return StubParsed()

    assert pq.run(10, None, 0, False, fetch=fetch, parse=parse) == {DONE: 1, SKIPPED: 0, FAILED: 1, pq.LOST: 0}


def test_stale_in_progress_reclaimed_fresh_not(temp_db):
    stale = add_row("pd1", status=IN_PROGRESS, attempts=1, locked_at=utcnow() - timedelta(minutes=16))
    fresh = add_row("pd2", status=IN_PROGRESS, attempts=1, locked_at=utcnow() - timedelta(minutes=5))
    assert pq.claim_batch(10) == [stale]
    assert get_row(stale).attempts == 2
    assert get_row(fresh).status == IN_PROGRESS


def test_stale_in_progress_on_last_attempt_becomes_failed(temp_db):
    row_id = add_row(status=IN_PROGRESS, attempts=3, locked_at=utcnow() - timedelta(hours=1))
    assert pq.claim_batch(10) == []
    assert get_row(row_id).status == FAILED


def test_claim_respects_limit_source_and_done(temp_db):
    a = add_row("pd1")
    add_row("pd2")
    add_row("pd3", status=DONE)
    with pq._tx() as s:
        s.add(BikeDiscovery(source="other.pl", source_product_id="x", raw_name="r", company="c", model="m"))
    assert pq.claim_batch(1, SOURCE) == [a]
    assert len(pq.claim_batch(10, SOURCE)) == 1
    assert pq.claim_batch(10, SOURCE) == []


def test_keyboard_interrupt_releases_rows(temp_db):
    ids = [add_row("pd1"), add_row("pd2")]

    def fetch(url):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        pq.run(10, None, 0, False, fetch=fetch, parse=stub_parse())
    for i in ids:
        row = get_row(i)
        assert (row.status, row.attempts, row.locked_at) == (PENDING, 0, None)


def test_dry_run_writes_nothing(temp_db, capsys):
    row_id = add_row()
    assert pq.dry_run(10, None, False, 0, fetch=fetch_ok, parse=stub_parse()) == 1
    row = get_row(row_id)
    assert (row.status, row.attempts, row.locked_at) == (PENDING, 0, None)
    assert bike_rows() == []
    assert "'Romet' 'Wagant 3'" in capsys.readouterr().out


def test_main_dry_run_cli(temp_db, monkeypatch):
    add_row()
    monkeypatch.setattr(pq, "http_fetch", fetch_ok)
    monkeypatch.setattr(pq, "_default_parse", stub_parse())
    assert pq.main(["--dry-run", "--delay", "0"]) == 0
    assert bike_rows() == []


# ── review fixes: save verification, per-row lease, fetch safety, DB target guard ──


def test_failed_save_is_failed_and_writes_nothing(temp_db, monkeypatch):
    with pq._tx() as s:
        s.add(models.Bike(brand="Romet", model="Wagant 3"))
    monkeypatch.setattr(repository, "save_bike_details", lambda *a, **k: None)  # swallowed failure
    row_id = add_row()
    assert claim_and_process(stub_parse()) == [FAILED]
    assert "save_bike_details stored nothing" in get_row(row_id).last_error
    with pq.session() as s:
        assert s.query(models.BikeDetails).count() == 0
    assert stored_photos("Romet", "Wagant 3") == []  # nothing half-written: photos come after the details


def test_saved_details_must_be_new(temp_db):
    """A details row older than the save start does not count as written (bike_store._saved_bike_id)."""
    import bike_store
    repository.save_bike_details("Romet", "Wagant 3", StubParsed().to_details_response("Romet", "Wagant 3"))
    assert bike_store._saved_bike_id("Romet", "Wagant 3", utcnow() - timedelta(minutes=1)) is not None
    assert bike_store._saved_bike_id("Romet", "Wagant 3", utcnow() + timedelta(minutes=1)) is None


def test_row_taken_over_before_start_is_left_alone(temp_db):
    row_id = add_row()
    claimed_at = utcnow()
    assert pq.claim_batch(10, now=claimed_at) == [row_id]
    other = claimed_at + timedelta(minutes=16)
    with pq._tx() as s:  # another run reclaimed it after our lease went stale
        s.get(BikeDiscovery, row_id).locked_at = other
    fetched = []
    result = pq.process_row(row_id, fetch=lambda url: fetched.append(url) or (200, ""), parse=stub_parse(),
                            claimed_at=claimed_at)
    assert result == pq.LOST and fetched == []
    row = get_row(row_id)
    assert (row.status, pq._aware(row.locked_at), row.bike_id) == (IN_PROGRESS, other, None)


def test_row_no_longer_in_progress_is_left_alone(temp_db):
    row_id = add_row(status=DONE)
    assert pq.process_row(row_id, fetch=fetch_ok, parse=stub_parse()) == pq.LOST
    assert get_row(row_id).status == DONE and bike_rows() == []


def test_finish_does_not_overwrite_a_takeover(temp_db):
    row_id = add_row()
    pq.claim_batch(10)
    other = utcnow() + timedelta(hours=1)

    def fetch(url):  # another run takes the row over while we fetch
        with pq._tx() as s:
            s.get(BikeDiscovery, row_id).locked_at = other
        return 200, "<html></html>"

    assert pq.process_row(row_id, fetch=fetch, parse=boom) == pq.LOST
    row = get_row(row_id)
    assert (row.status, row.last_error, row.next_attempt_at) == (IN_PROGRESS, None, None)
    assert pq._aware(row.locked_at) == other


def test_run_counts_are_exact_with_claim_lease(temp_db):
    add_row("pd1")
    assert pq.run(10, None, 0, False, fetch=fetch_ok, parse=stub_parse()) == {
        DONE: 1, SKIPPED: 0, FAILED: 0, pq.LOST: 0}


@pytest.mark.parametrize("url", [
    "http://www.centrumrowerowe.pl/rower-pd1/",
    "https://evil.example.com/rower-pd1/",
    "https://www.centrumrowerowe.pl.evil.com/rower-pd1/",
    "https://www.centrumrowerowe.pl:8443/rower-pd1/",
    "file:///etc/passwd",
])
def test_unsafe_url_fails_without_fetch(temp_db, url):
    row_id = add_row()
    with pq._tx() as s:
        s.get(BikeDiscovery, row_id).details_link = url
    fetched = []
    assert claim_and_process(stub_parse(), fetch=lambda u: fetched.append(u) or (200, "")) == [FAILED]
    assert fetched == []
    assert get_row(row_id).last_error.startswith("UnsafeURL: refusing to fetch")


def mock_transport(routes, seen):
    import httpx

    def handler(request):
        seen.append((str(request.url), request.headers.get("user-agent")))
        status, headers, body = routes[str(request.url)]
        return httpx.Response(status, headers=headers, text=body)

    return httpx.MockTransport(handler)


BASE = "https://www.centrumrowerowe.pl"


def test_http_fetch_follows_same_host_redirects():
    seen = []
    routes = {
        f"{BASE}/a": (301, {"location": "https://centrumrowerowe.pl/b"}, ""),
        "https://centrumrowerowe.pl/b": (302, {"location": "/c"}, ""),
        "https://centrumrowerowe.pl/c": (200, {}, "<html>ok</html>"),
    }
    assert pq.http_fetch(f"{BASE}/a", transport=mock_transport(routes, seen)) == (200, "<html>ok</html>")
    assert [u for u, _ in seen] == [f"{BASE}/a", "https://centrumrowerowe.pl/b", "https://centrumrowerowe.pl/c"]
    assert all(ua == pq.UA["User-Agent"] for _, ua in seen)


def test_http_fetch_refuses_redirect_off_site():
    seen = []
    routes = {f"{BASE}/a": (302, {"location": "https://evil.example.com/x"}, "")}
    with pytest.raises(pq.UnsafeURL):
        pq.http_fetch(f"{BASE}/a", transport=mock_transport(routes, seen))
    assert [u for u, _ in seen] == [f"{BASE}/a"]


def test_http_fetch_refuses_https_to_http_downgrade():
    routes = {f"{BASE}/a": (301, {"location": "http://www.centrumrowerowe.pl/a"}, "")}
    with pytest.raises(pq.UnsafeURL):
        pq.http_fetch(f"{BASE}/a", transport=mock_transport(routes, []))


def test_http_fetch_redirect_limit():
    seen = []
    routes = {f"{BASE}/{i}": (302, {"location": f"/{i + 1}"}, "") for i in range(10)}
    with pytest.raises(pq.FetchError, match="more than 3 redirects"):
        pq.http_fetch(f"{BASE}/0", transport=mock_transport(routes, seen))
    assert len(seen) == 4  # the page + 3 redirects


def test_http_fetch_returns_404_as_is():
    routes = {f"{BASE}/gone": (404, {}, "not found")}
    assert pq.http_fetch(f"{BASE}/gone", transport=mock_transport(routes, [])) == (404, "not found")


def test_main_checks_db_target(temp_db, monkeypatch):
    calls = []

    def check_target(allow_remote=False):
        calls.append(allow_remote)
        if not allow_remote:
            raise SystemExit("Refusing to write to a non-local database")
        return "postgresql://remote"

    monkeypatch.setattr(pq.db, "check_target", check_target)
    monkeypatch.setattr(pq, "http_fetch", fetch_ok)
    monkeypatch.setattr(pq, "_default_parse", stub_parse())
    row_id = add_row()
    with pytest.raises(SystemExit):
        pq.main(["--delay", "0"])
    assert get_row(row_id).status == PENDING  # refused before anything was claimed
    assert pq.main(["--dry-run", "--delay", "0"]) == 0  # dry run only prints the target
    assert pq.main(["--allow-remote", "--delay", "0"]) == 0
    assert calls == [False, True, True]
    assert get_row(row_id).status == DONE


def test_main_on_local_sqlite_passes_real_check_target(temp_db, monkeypatch):
    monkeypatch.setattr(pq, "http_fetch", fetch_ok)
    monkeypatch.setattr(pq, "_default_parse", stub_parse())
    add_row()
    assert pq.main(["--delay", "0"]) == 0
    assert len(bike_rows()) == 1
