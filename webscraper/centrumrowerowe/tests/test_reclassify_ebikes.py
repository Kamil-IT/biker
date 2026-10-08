"""reclassify_ebikes.py (TODO-047): an 'Electric' bike gets the type its product page names."""
from pathlib import Path

import process_queue as pq
import reclassify_ebikes as rc
from db import DONE, models
from product_parser import parse_product, shop_category
from test_process_queue import StubParsed, add_row, claim_and_process

FIXTURES = Path(__file__).parent / "fixtures"
TREKKING = (FIXTURES / "ebike_haibike_trekking_3_high.html").read_text(encoding="utf-8")
CITY = (FIXTURES / "ebike_le_grand_elille_3.html").read_text(encoding="utf-8")
URL_A = "https://www.centrumrowerowe.pl/rower-a-pd1/"
URL_B = "https://www.centrumrowerowe.pl/rower-b-pd2/"


def fetch_from(pages: dict):
    def fetch(url):
        return (200, pages[url]) if url in pages else (404, "")
    return fetch


def bike(model: str, bike_type: str, pid: str, url: str, category=None) -> int:
    with pq._tx() as s:
        b = models.Bike(brand="Haibike", model=model)
        s.add(b)
        s.flush()
        bike_id = b.id
    add_row(pid=pid, model=model, url=url, bike_type=bike_type, status=DONE, bike_id=bike_id)
    if category is not None:  # an old value: ck_bike_category would refuse it, as on a pre-TODO-047 database
        with models.get_engine().connect() as c:
            c.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
            c.exec_driver_sql("UPDATE bike SET category = ? WHERE id = ?", (category, bike_id))
            c.commit()
            c.exec_driver_sql("PRAGMA ignore_check_constraints = OFF")
    return bike_id


def category(bike_id):
    with pq.session() as s:
        return s.get(models.Bike, bike_id).category


def test_the_parser_keeps_the_shop_category():
    assert shop_category(TREKKING) == "Rowery > Elektryczne > Trekkingowe"
    assert parse_product(CITY, URL_B).shop_category == "Rowery > Elektryczne > Miejskie"


def test_electric_and_null_ebikes_get_the_page_type(temp_db):
    electric = bike("Trekking 3", "elektryczny", "pd1", URL_A, category="Electric")
    null = bike("eLille 3", "elektryczny", "pd2", URL_B)
    other = bike("Trans", "trekkingowy", "pd3", "https://www.centrumrowerowe.pl/rower-c-pd3/")
    counts = rc.run(None, 0, dry_run=False, fetch=fetch_from({URL_A: TREKKING, URL_B: CITY}))
    assert category(electric) == "Touring" and category(null) == "City/Cross/Hybrid"
    assert category(other) is None, "a non-e-bike is no candidate"
    assert counts == {"Touring": 1, "City/Cross/Hybrid": 1}
    assert rc.candidates() == [], "a second run finds nothing to do"


def test_cargo_without_a_page_and_unresolved_bikes(temp_db):
    cargo = bike("Cargo", "elektryczny cargo", "pd1", URL_A, category="Electric cargo")
    gone = bike("Gone", "elektryczny", "pd2", URL_B, category="Electric")
    counts = rc.run(None, 0, dry_run=False, fetch=fetch_from({}))
    assert category(cargo) == "City/Cross/Hybrid"
    assert category(gone) == "Electric", "an unresolved bike is left alone"
    assert counts == {"City/Cross/Hybrid": 1, rc.UNRESOLVED: 1}


def test_dry_run_writes_nothing(temp_db):
    electric = bike("Trekking 3", "elektryczny", "pd1", URL_A, category="Electric")
    counts = rc.run(None, 0, dry_run=True, fetch=fetch_from({URL_A: TREKKING}))
    assert counts == {"Touring": 1} and category(electric) == "Electric"


def test_the_queue_types_a_new_ebike_from_its_page(temp_db):
    def parse(html, url):
        p = StubParsed("Haibike", "AllTrail 6")
        p.bike_type, p.shop_category = "elektryczny", "Rowery > Elektryczne > Górskie MTB"
        return p
    add_row(pid="pd9", model="AllTrail 6", bike_type="elektryczny")
    assert claim_and_process(parse) == [DONE]
    with pq.session() as s:
        assert s.query(models.Bike.category).filter_by(model="AllTrail 6").scalar() == "MTB"


def test_a_category_set_meanwhile_is_not_overwritten(temp_db):
    electric = bike("Trekking 3", "elektryczny", "pd1", URL_A, category="Electric")
    assert rc.write(electric, None, "MTB") is False, "the row no longer holds the value read"
    assert category(electric) == "Electric"
    assert rc.write(electric, "Electric", "Touring") is True and category(electric) == "Touring"
