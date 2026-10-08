"""Unit tests for the frame-size calculator (app/frame_size.py) and its endpoint POST /v1/fit/frame-size
(app/fit_routes.py) — pure calculation, no server, no database, no network, no AI call.
Run: cd backend && pytest   (collected via pytest.ini)"""
import sys
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main  # noqa: E402
from app.frame_size import compute_frame_size, letter_for  # noqa: E402
from app.schemas import FIT_BIKE_TYPES  # noqa: E402

client = TestClient(main.app)  # no `with`: the lifespan (database init) is not needed


def test_control_example_road():
    r = compute_frame_size(178, 80, "Road")
    assert r.model_dump() == {
        "bike_type": "Road", "size": 52.8, "unit": "cm", "range_min": 50.8, "range_max": 54.8,
        "letter": "S", "letters": ["S", "M"], "confidence": "good", "measurement_warning": False,
    }


def test_mtb_is_in_inches():
    r = compute_frame_size(178, 80, "MTB")  # 80 * 0.226 = 18.08
    assert (r.size, r.unit, r.range_min, r.range_max) == (18.1, "in", 17.3, 18.9)
    assert (r.letter, r.letters, r.confidence) == ("M", ["M"], "good")


def test_gravel_subtracts_one_and_is_medium():
    r = compute_frame_size(178, 80, "Gravel")  # 80 * 0.65 - 1 = 51.0
    assert (r.size, r.unit, r.range_min, r.range_max) == (51.0, "cm", 49.0, 53.0)
    assert (r.letter, r.confidence) == ("S", "medium")


@pytest.mark.parametrize("bike_type", ["Touring", "City/Cross/Hybrid"])
def test_touring_and_hybrid_use_the_road_multiplier_but_are_medium(bike_type):
    r = compute_frame_size(178, 80, bike_type)  # 80 * 0.66 = 52.8
    assert (r.size, r.unit, r.range_min, r.range_max, r.letter) == (52.8, "cm", 50.8, 54.8, "S")
    assert r.confidence == "medium"


def test_every_bike_type_has_a_formula():
    for bike_type in FIT_BIKE_TYPES:
        assert compute_frame_size(175, 80, bike_type).bike_type == bike_type


@pytest.mark.parametrize("size, letter", [
    (49.99, "XS"), (50.0, "S"), (52.99, "S"), (53.0, "M"), (55.99, "M"), (56.0, "L"), (58.99, "L"), (59.0, "XL"), (70.0, "XL"),
])
def test_letter_bounds_in_cm(size, letter):
    assert letter_for(size, "cm") == letter


@pytest.mark.parametrize("size, letter", [
    (14.99, "XS"), (15.0, "S"), (16.99, "S"), (17.0, "M"), (18.99, "M"), (19.0, "L"), (20.99, "L"), (21.0, "XL"), (25.0, "XL"),
])
def test_letter_bounds_in_inches(size, letter):
    assert letter_for(size, "in") == letter


def test_letters_come_from_the_rounded_values():
    r = compute_frame_size(178, 80.3, "Road")  # 52.998 is shown as 53.0, so it must read M, never S
    assert (r.size, r.letter) == (53.0, "M")
    assert (r.range_min, r.range_max, r.letters) == (51.0, 55.0, ["S", "M"])
    # the same below a bound: 49.99995 is shown as 50.0, so it is an S, not an XS
    r = compute_frame_size(178, 75.7575, "Road")
    assert (r.size, r.letter) == (50.0, "S")


def test_exact_halves_round_up_not_down():
    road = compute_frame_size(165, 62.5, "Road")  # 41.25 exactly: 41.3, not the float's 41.2
    assert (road.size, road.range_min, road.range_max, road.letter) == (41.3, 39.3, 43.3, "XS")
    mtb = compute_frame_size(178, 75.0, "MTB")  # 16.95 exactly: 17.0 in, which is an M, not an S
    assert (mtb.size, mtb.range_min, mtb.range_max, mtb.letter, mtb.letters) == (17.0, 16.2, 17.8, "M", ["S", "M"])
    gravel = compute_frame_size(170, 61, "Gravel")  # 61 * 0.65 - 1 = 38.65 exactly: 38.7
    assert (gravel.size, gravel.range_min, gravel.range_max) == (38.7, 36.7, 40.7)


# An oracle written separately from app/frame_size.py: its own constants, exact integer / Fraction arithmetic.
ORACLE_FORMULAS = {  # bike type -> (multiplier, offset, unit, half range)
    "Road": ("0.66", "0", "cm", "2"),
    "MTB": ("0.226", "0", "in", "0.8"),
    "Gravel": ("0.65", "-1", "cm", "2"),
    "Touring": ("0.66", "0", "cm", "2"),
    "City/Cross/Hybrid": ("0.66", "0", "cm", "2"),
}
ORACLE_LETTERS = {  # unit -> (letter, lower bound), ascending
    "cm": [("XS", None), ("S", Decimal("50")), ("M", Decimal("53")), ("L", Decimal("56")), ("XL", Decimal("59"))],
    "in": [("XS", None), ("S", Decimal("15")), ("M", Decimal("17")), ("L", Decimal("19")), ("XL", Decimal("21"))],
}


def _oracle_round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _oracle_letter(value: Decimal, unit: str) -> str:
    letter = "XS"
    for name, bound in ORACLE_LETTERS[unit]:
        if bound is not None and value >= bound:
            letter = name
    return letter


def _oracle(height_tenths: int, inseam_tenths: int, bike_type: str) -> dict:
    mult, offset, unit, half = ORACLE_FORMULAS[bike_type]
    raw = Decimal(inseam_tenths) / 10 * Decimal(mult) + Decimal(offset)
    size, low, high = _oracle_round(raw), _oracle_round(raw - Decimal(half)), _oracle_round(raw + Decimal(half))
    names = [n for n, _ in ORACLE_LETTERS[unit]]
    ratio = Fraction(inseam_tenths, height_tenths)  # exact
    return {
        "size": float(size), "range_min": float(low), "range_max": float(high), "unit": unit,
        "letter": _oracle_letter(size, unit),
        "letters": names[names.index(_oracle_letter(low, unit)):names.index(_oracle_letter(high, unit)) + 1],
        "measurement_warning": not Fraction(2, 5) <= ratio <= Fraction(1, 2),
    }


@pytest.mark.parametrize("bike_type", FIT_BIKE_TYPES)
@pytest.mark.parametrize("height_tenths", [1500, 1785, 2000])
def test_every_inseam_in_tenths_matches_the_decimal_oracle(bike_type, height_tenths):
    for inseam_tenths in range(600, 1101):  # 60.0 ... 110.0 cm, step 0.1
        got = compute_frame_size(height_tenths / 10, inseam_tenths / 10, bike_type).model_dump()
        want = _oracle(height_tenths, inseam_tenths, bike_type)
        assert {k: got[k] for k in want} == want, f"{bike_type} height={height_tenths / 10} inseam={inseam_tenths / 10}"


def test_output_numbers_are_rounded_to_one_decimal():
    r = compute_frame_size(173.3, 79.7, "MTB")
    for v in (r.size, r.range_min, r.range_max):
        assert v == round(v, 1)


def test_letters_with_one_entry():
    low = compute_frame_size(150, 60, "Road")  # 39.6, range 37.6-41.6
    assert (low.letter, low.letters) == ("XS", ["XS"])
    high = compute_frame_size(205, 110, "Road")  # 72.6, range 70.6-74.6
    assert (high.letter, high.letters) == ("XL", ["XL"])


def test_letters_with_two_entries():
    assert compute_frame_size(178, 80, "Road").letters == ["S", "M"]


def test_letters_with_three_entries_and_the_range_end_on_a_bound():
    mid = compute_frame_size(180, 83, "Touring")  # 54.78, range 52.78-56.78
    assert (mid.letter, mid.letters) == ("M", ["S", "M", "L"])
    # range_max lands exactly on 53.0, which is already an M
    edge = compute_frame_size(178, 80, "Gravel")  # 51.0, range 49.0-53.0
    assert edge.letters == ["XS", "S", "M"]


def test_letters_are_ascending_and_contain_the_main_letter():
    for bike_type in FIT_BIKE_TYPES:
        for inseam in range(60, 111, 5):
            r = compute_frame_size(180, inseam, bike_type)
            order = ["XS", "S", "M", "L", "XL"]
            assert r.letters == sorted(r.letters, key=order.index)
            assert r.letter in r.letters
            assert 1 <= len(r.letters) <= 3


@pytest.mark.parametrize("height, inseam", [(178, 70), (200, 79), (160, 62)])
def test_warning_below_the_ratio_range(height, inseam):
    assert compute_frame_size(height, inseam, "Road").measurement_warning is True


@pytest.mark.parametrize("height, inseam", [(178, 90), (178, 95), (150, 76)])
def test_warning_above_the_ratio_range(height, inseam):
    assert compute_frame_size(height, inseam, "Road").measurement_warning is True


@pytest.mark.parametrize("height, inseam", [
    (180, 72),     # exactly 0.40
    (180, 90),     # exactly 0.50
    (171.5, 68.6),  # 0.4 on paper, 0.39999999999999997 as a float
    (172, 68.8),
    (178, 80),
])
def test_no_warning_on_the_boundaries_and_inside(height, inseam):
    assert compute_frame_size(height, inseam, "Road").measurement_warning is False


def test_a_warning_does_not_change_the_result():
    odd = compute_frame_size(178, 95, "Road")
    assert odd.measurement_warning is True
    assert (odd.size, odd.letter) == (62.7, "XL")


CONTROL_BODY = {"height_cm": 178, "inseam_cm": 80, "bike_type": "Road"}


def test_endpoint_control_example():
    resp = client.post("/v1/fit/frame-size", json=CONTROL_BODY)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "bike_type": "Road", "size": 52.8, "unit": "cm", "range_min": 50.8, "range_max": 54.8,
        "letter": "S", "letters": ["S", "M"], "confidence": "good", "measurement_warning": False,
    }


def test_endpoint_mtb_is_in_inches():
    body = client.post("/v1/fit/frame-size", json={**CONTROL_BODY, "bike_type": "MTB"}).json()
    assert (body["size"], body["unit"], body["letter"]) == (18.1, "in", "M")


@pytest.mark.parametrize("height, inseam", [(140, 60), (210, 110), (140.0, 110.0)])
def test_endpoint_accepts_the_limits(height, inseam):
    resp = client.post("/v1/fit/frame-size", json={"height_cm": height, "inseam_cm": inseam, "bike_type": "Road"})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("patch", [
    {"height_cm": 139.9}, {"height_cm": 210.1}, {"height_cm": 0}, {"height_cm": -170},
    {"inseam_cm": 59.9}, {"inseam_cm": 110.1}, {"inseam_cm": 111},
    {"bike_type": "BMX"}, {"bike_type": "road"}, {"bike_type": ""}, {"bike_type": "Hybrid/Commuter"},
    {"height_cm": "tall"}, {"inseam_cm": None}, {"bike_type": None},
])
def test_endpoint_rejects_bad_fields_with_422(patch):
    assert client.post("/v1/fit/frame-size", json={**CONTROL_BODY, **patch}).status_code == 422


@pytest.mark.parametrize("missing", ["height_cm", "inseam_cm", "bike_type"])
def test_endpoint_rejects_a_missing_field_with_422(missing):
    body = {k: v for k, v in CONTROL_BODY.items() if k != missing}
    assert client.post("/v1/fit/frame-size", json=body).status_code == 422


@pytest.mark.parametrize("raw", [
    '{"height_cm": NaN, "inseam_cm": 80, "bike_type": "Road"}',
    '{"height_cm": 178, "inseam_cm": Infinity, "bike_type": "Road"}',
    '{"height_cm": 178, "inseam_cm": -Infinity, "bike_type": "Road"}',
])
def test_endpoint_rejects_nan_and_infinity_with_422(raw):
    resp = client.post("/v1/fit/frame-size", content=raw, headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    assert resp.json()["detail"]  # the offending NaN is not echoed back (it would not serialise: a 500)
