"""process_queue.py writes the generic /v1/bike/details cache (the only thing that endpoint reads)."""
import process_queue as pq
from app import cache
from app.schemas import BikeDetailsResponse
from db import DONE, BikeDiscoveryListing, models, repository
from test_process_queue import StubParsed, add_row, bike_rows, claim_and_process, get_row, stub_parse

EP = pq.DETAILS_ENDPOINT


def cached(company, model):
    return cache.get_cached(EP, {"company": company, "model": model}, BikeDetailsResponse)


def cache_rows():
    with pq.session() as s:
        return s.query(models.endpoint_req_to_body_cache).count()


def test_happy_path_writes_cache_for_stored_casing(temp_db):
    with pq._tx() as s:
        s.add(models.Bike(brand="Romet", model="Wagant 3"))
    add_row()
    assert claim_and_process(stub_parse("ROMET", "WAGANT 3")) == [DONE]
    hit = cached("Romet", "Wagant 3")
    assert hit is not None
    assert (hit.company, hit.model) == ("Romet", "Wagant 3")  # the bike row's casing, not the page's
    assert hit == repository.get_bike_details("Romet", "Wagant 3")
    assert cache_rows() == 1


def test_existing_cache_entry_is_kept(temp_db):
    ai_made = StubParsed().to_details_response("Romet", "Wagant 3").model_copy(update={"components": []})
    cache.set_cached(EP, {"company": "Romet", "model": "Wagant 3"}, ai_made)
    add_row()
    assert claim_and_process(stub_parse()) == [DONE]
    assert cached("Romet", "Wagant 3").components == []
    assert cache_rows() == 1


def test_cache_failure_leaves_row_done(temp_db, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("cache down")

    monkeypatch.setattr(cache, "set_cached", broken)
    row_id = add_row()
    assert claim_and_process(stub_parse()) == [DONE]
    row = get_row(row_id)
    assert (row.status, row.last_error) == (DONE, None)
    assert repository.get_bike_details("Romet", "Wagant 3") is not None
    assert cached("Romet", "Wagant 3") is None


def test_swallowed_cache_failure_reported_as_failed(temp_db, monkeypatch):
    monkeypatch.setattr(cache, "set_cached", lambda *a, **k: None)  # set_cached logs and swallows DB errors
    response = StubParsed().to_details_response("Romet", "Wagant 3")
    assert pq.cache_details("Romet", "Wagant 3", response) == pq.CACHE_FAILED


def _done_bike_without_cache(pid, brand, model, no_details=False):
    repository.save_bike_details(brand, model, StubParsed(brand, model).to_details_response(brand, model))
    with pq._tx() as s:
        bike_id = repository._find_bike_id(s, brand, model)
        if no_details:  # e.g. deleted by hand after processing
            detail_id = s.query(models.BikeDetails.id).filter_by(bike_id=bike_id).scalar()
            s.query(models.BikeDetailComponent).filter_by(bike_detail_id=detail_id).delete()
            s.query(models.BikeDetails).filter_by(id=detail_id).delete()
    add_row(pid, status=DONE, bike_id=bike_id)


def test_sync_cache_fills_done_rows_and_is_idempotent(temp_db, capsys):
    _done_bike_without_cache("pd1", "Romet", "Wagant 3")
    _done_bike_without_cache("pd2", "Focus", "Whistler 3.6")
    _done_bike_without_cache("pd3", "Kross", "Old", no_details=True)
    add_row("pd4")  # pending, no bike: ignored
    assert pq.sync_cache(None, dry_run=True) == {"written": 2, "present": 0, "missing": 1, "failed": 0}
    assert cache_rows() == 0  # the dry run wrote nothing
    assert pq.sync_cache(None) == {"written": 2, "present": 0, "missing": 1, "failed": 0}
    assert cached("Focus", "Whistler 3.6").model == "Whistler 3.6"
    assert pq.sync_cache(None) == {"written": 0, "present": 2, "missing": 1, "failed": 0}
    assert cache_rows() == 2
    assert get_row(1).status == DONE and len(bike_rows()) == 3


def test_sync_cache_respects_source(temp_db):
    _done_bike_without_cache("pd1", "Romet", "Wagant 3")
    with pq._tx() as s:
        s.query(BikeDiscoveryListing).update({BikeDiscoveryListing.source: "other.pl"})
    assert pq.sync_cache("centrumrowerowe.pl")["written"] == 0
    assert pq.sync_cache("other.pl")["written"] == 1


def test_main_sync_cache_no_fetch_and_guarded(temp_db, monkeypatch, capsys):
    _done_bike_without_cache("pd1", "Romet", "Wagant 3")
    add_row("pd2")
    calls = []
    monkeypatch.setattr(pq.db, "check_target", lambda allow_remote=False: calls.append(allow_remote) or "sqlite")
    monkeypatch.setattr(pq, "http_fetch", lambda url: (_ for _ in ()).throw(AssertionError("fetched")))
    assert pq.main(["--sync-cache", "--dry-run"]) == 0
    assert "would write=1" in capsys.readouterr().out and cache_rows() == 0
    assert pq.main(["--sync-cache"]) == 0
    assert "written=1" in capsys.readouterr().out and cache_rows() == 1
    assert calls == [True, False]
    assert get_row(2).status == "pending"  # nothing claimed
