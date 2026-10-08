"""enrich.py fills bike.category from the discovery bike_type (free step, only while NULL and mapped)."""
import argparse

import enrich
import process_queue as pq
from db import DONE, models
from test_process_queue import add_row


def bike_with_row(bike_type, category=None):
    with pq._tx() as s:
        bike = models.Bike(brand="Romet", model="Wagant 3", category=category)
        s.add(bike)
        s.flush()
        bike_id = bike.id
    row_id = add_row(bike_type=bike_type, status=DONE, bike_id=bike_id)
    return row_id, bike_id


def category(bike_id):
    with pq.session() as s:
        return s.get(models.Bike, bike_id).category


def enrich_free(row_id, bike_id):
    """enrich_bike with every paid step already given up and the guard closed: only the free steps run."""
    attempts = argparse.Namespace(gave_up=lambda b, step: True, record=lambda *a: None)
    guard = argparse.Namespace(allow=lambda: False)
    ctx = argparse.Namespace(attempts=attempts, guard=guard, refresh_short=False, backend="http://unused")
    return enrich.enrich_bike(row_id, bike_id, ctx)


def test_mapped_type_fills_a_null_category(temp_db):
    row_id, bike_id = bike_with_row("trekkingowy")
    assert enrich.missing(bike_id, row_id)["category"] is True
    out = enrich_free(row_id, bike_id)
    assert out["category"] == "Touring" and category(bike_id) == "Touring"
    assert enrich.missing(bike_id, row_id)["category"] is False


def test_existing_category_is_never_overwritten(temp_db):
    row_id, bike_id = bike_with_row("szosowy", category="Gravel")
    assert enrich.missing(bike_id, row_id)["category"] is False
    assert "category" not in enrich_free(row_id, bike_id)
    assert category(bike_id) == "Gravel"


def test_unmapped_or_missing_type_does_not_keep_the_bike_open(temp_db):
    for i, bike_type in enumerate(("hulajnoga", None)):
        with pq._tx() as s:
            bike = models.Bike(brand="Romet", model=f"X {i}")
            s.add(bike)
            s.flush()
            bike_id = bike.id
        row_id = add_row(pid=f"pd{i}", bike_type=bike_type, status=DONE, bike_id=bike_id)
        assert enrich.missing(bike_id, row_id)["category"] is False
        assert category(bike_id) is None
