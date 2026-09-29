"""product_parser on saved centrumrowerowe.pl pages — no network, no DB."""
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import product_parser as pp  # noqa: E402
from product_parser import ParseError, parse_product  # noqa: E402
from app import models, repository  # noqa: E402 — product_parser put backend/ on sys.path
from app.schemas import BikeDetailsResponse  # noqa: E402

FIXTURES = HERE / "fixtures"
BASE = "https://www.centrumrowerowe.pl"

# fixture → (url, brand, model, bike_type, wheel, sizes, electric)
CASES = {
    "trekking_romet_wagant_3.html": (
        f"{BASE}/rower-trekkingowy-romet-wagant-3-pd27404/",
        "Romet", "Wagant 3", "trekkingowy", '28"', ["M", "L", "XL", '19"'], False,
    ),
    "mtb_focus_whistler_3_6.html": (
        f"{BASE}/rower-mtb-focus-whistler-3-6-pd37036/",
        "Focus", "Whistler 3.6", "MTB", '29"', ["M", "L", "XL", '18"'], False,
    ),
    "ebike_haibike_trekking_3_high.html": (
        f"{BASE}/rower-elektryczny-haibike-trekking-3-high-pd33855/",
        "Haibike", "Trekking 3 High", "elektryczny", '27.5"', ["S", "XL", '19"'], True,
    ),
    "ebike_le_grand_elille_3.html": (
        f"{BASE}/rower-elektryczny-le-grand-elille-3-pd57512/",
        "Le Grand", "eLille 3", "elektryczny", '28"', ["M", "L", '17"'], True,
    ),
}


def _parse(name):
    return parse_product((FIXTURES / name).read_text(encoding="utf-8"), CASES[name][0])


def _page(rows, name="Rower MTB KROSS Level 1.0", brand=None, ld=None, section="Rama"):
    """A minimal product page: JSON-LD Product + one Specyfikacja section."""
    product = {"@context": "http://schema.org", "@type": "Product", "name": name,
               "brand": {"@type": "Brand", "name": brand if brand is not None else "KROSS"}}
    product.update(ld or {})
    items = "".join(f'<li><span class="label">{k}</span><span class="value">{v}</span></li>' for k, v in rows)
    return (f'<script type="application/ld+json">{json.dumps(product, ensure_ascii=False)}</script>'
            f'<div class="section product-spec"><div class="prod-feature"><button class="h3">{section}</button>'
            f'<ul>{items}</ul></div></div>')


def _specs(parsed) -> "repository._BikeSpecs":
    """The rows find_bikes_by_details would read back from bike_detail_component."""
    specs = repository._BikeSpecs()
    for cat in parsed.to_details_response(parsed.brand, parsed.model).components:
        for sub in cat.subcategories:
            for el in sub.elements:
                specs.categories.add(cat.category)
                for s in el.specs or [None]:
                    specs.rows.append((cat.category, sub.subcategory, el.name, s.key if s else "", s.value if s else ""))
    return specs


def _categories(parsed):
    return {c.category for c in parsed.components}


def _elements(parsed, category):
    return [(s.subcategory, e) for c in parsed.components if c.category == category
            for s in c.subcategories for e in s.elements]


@pytest.mark.parametrize("name", CASES)
def test_identity(name):
    _, brand, model, bike_type, *_ = CASES[name]
    p = _parse(name)
    assert (p.brand, p.model, p.bike_type) == (brand, model, bike_type)
    assert p.raw_name.lower().startswith("rower")


@pytest.mark.parametrize("name", CASES)
def test_description_is_polish_and_short(name):
    p = _parse(name)
    assert p.description
    assert re.search(r"[ąćęłńóśźż]", p.description.lower()) or " rower" in p.description.lower()
    assert len(pp._SENTENCE_END.split(p.description)) <= pp.MAX_SENTENCES
    assert " ," not in p.description and " ." not in p.description
    assert p.description.rstrip()[-1] in ".!?…"  # punctuation kept, not stripped
    resp = p.to_details_response(p.brand, p.model)
    assert resp.description.text == p.description
    assert resp.description.citations == []


@pytest.mark.parametrize("name", CASES)
def test_photos(name):
    p = _parse(name)
    assert 1 <= len(p.photos) <= pp.MAX_PHOTOS
    assert len(set(p.photos)) == len(p.photos)
    assert all(u.startswith("https://www.centrumrowerowe.pl/photo/") for u in p.photos)


@pytest.mark.parametrize("name", CASES)
def test_expected_categories(name):
    cats = _categories(_parse(name))
    assert {"Frame", "Drivetrain", "Brakes", "Wheels", "Saddle & Seatpost", "Accessories"} <= cats
    assert cats <= set(pp.sm.CATEGORY_ORDER)


@pytest.mark.parametrize("name", CASES)
def test_electric_category_only_on_ebikes(name):
    *_, electric = CASES[name]
    p = _parse(name)
    assert p.is_electric is electric
    assert ("Electric / Powertrain" in _categories(p)) is electric
    assert repository._MATCHERS["is_electric"](_specs(p), electric)
    assert not repository._MATCHERS["is_electric"](_specs(p), not electric)


@pytest.mark.parametrize("name", CASES)
def test_wheel_and_frame_sizes_match_db_first_search(name):
    *_, wheel, sizes, _ = CASES[name]
    p = _parse(name)
    specs = _specs(p)
    assert p.frame_sizes == sizes
    assert specs.values("sizes", "Frame", "Frame") == [", ".join(sizes)]
    assert repository._match_wheel(specs, wheel)
    assert not repository._match_wheel(specs, '20"')
    for size in sizes:
        assert repository._match_frame_size(specs, size)
    for absent in ("XXL", "XS", '15"', '21"'):
        assert not repository._match_frame_size(specs, absent)


def test_all_variant_sizes_not_only_the_shown_one():
    # The Wagant page shows the M / 19" variant; L and XL come from the variant selector.
    specs = _specs(_parse("trekking_romet_wagant_3.html"))
    assert specs.values("sizes", "Frame", "Frame") == ['M, L, XL, 19"']
    assert specs.values("frame size", "Frame", "Frame") == ['19"']
    assert repository._match_frame_size(specs, "L")
    assert repository._match_frame_size(specs, '19"')
    assert not repository._match_frame_size(specs, "S")


@pytest.mark.parametrize("rows, sizes", [
    ([("Rozmiar producenta", "S"), ("Rozmiar ramy", '15,5"')], ["S", '15.5"']),
    ([("Rozmiar ramy", '17"')], ['17"']),
    ([("Rozmiar producenta", "M (170-178 cm)")], ["M"]),
    ([("Rozmiar ramy", "54 cm")], ["54cm"]),
])
def test_single_variant_page_falls_back_to_the_table(rows, sizes):
    p = parse_product(_page(rows + [("Materiał ramy", "aluminium")]), BASE + "/x/")
    specs = _specs(p)
    assert p.frame_sizes == sizes
    for size in sizes:
        assert repository._match_frame_size(specs, size)
    assert not repository._match_frame_size(specs, "XL")
    if '15.5"' in sizes:  # the decimal comma must not split into a false '15' size
        assert not repository._match_frame_size(specs, "15")


def test_no_size_on_page_means_no_sizes_row():
    p = parse_product(_page([("Materiał ramy", "stal")]), BASE + "/x/")
    assert p.frame_sizes == []
    assert _specs(p).values("sizes", "Frame", "Frame") == []


def test_ebike_motor_and_battery_rows():
    p = _parse("ebike_haibike_trekking_3_high.html")
    subs = dict(_elements(p, "Electric / Powertrain"))
    assert subs["Motor"].name == "Bosch Performance Line Gen.3"
    motor_specs = {s.key: s.value for s in subs["Motor"].specs}
    assert motor_specs["Torque"] == "60 Nm" and motor_specs["Power"] == "250W"
    assert {s.key: s.value for s in subs["Battery"].specs}["Capacity"] == "500 Wh"


def test_electric_labels_on_a_plain_bike_go_to_accessories():
    rows = [("Rozmiar ramy", '19"'), ("Wyświetlacz", "Sigma BC 5.0"), ("Napięcie", "6 V")]
    p = parse_product(_page(rows, section="Komponenty"), BASE + "/x/")
    assert not p.is_electric
    assert "Electric / Powertrain" not in _categories(p)
    other = [(e.name, e.description) for s, e in _elements(p, "Accessories") if s == pp.sm.UNKNOWN_SUBCATEGORY]
    assert other == [("Sigma BC 5.0", "Wyświetlacz"), ("6 V", "Napięcie")]


def test_electric_labels_on_an_ebike_by_name_go_to_powertrain():
    rows = [("Wyświetlacz", "Bafang DP C07"), ("Napięcie", "36 V")]
    p = parse_product(_page(rows, name="Rower elektryczny KROSS Trans Hybrid 4.0", section="Komponenty"),
                      BASE + "/x/")
    assert p.is_electric
    subs = dict(_elements(p, "Electric / Powertrain"))
    assert subs["Display"].name == "Bafang DP C07"
    assert {s.key: s.value for s in subs["Battery"].specs} == {"Voltage": "36 V"}


def test_values_are_kept_as_written():
    p = _parse("trekking_romet_wagant_3.html")
    names = {(s.subcategory, e.name) for c in p.components for s in c.subcategories for e in s.elements}
    assert ("Rear Derailleur", "Shimano Acera RD-M3020, 7s") in names
    assert ("Fork", "SR Suntour M3010") in names
    # Shop bookkeeping rows are dropped, not dumped into Accessories.
    assert not any("5904803170203" in e.name for c in p.components for s in c.subcategories for e in s.elements)


def test_unknown_keys_land_in_accessories():
    html = (FIXTURES / "trekking_romet_wagant_3.html").read_text(encoding="utf-8")
    extra = ('<li><span class="label">Magiczny dodatek</span>'
             '<span class="value">Tęczowy proporczyk</span></li>')
    html = html.replace('<span class="label" title="Widelec">', extra + '<li><span class="label" title="Widelec">', 1)
    p = parse_product(html, CASES["trekking_romet_wagant_3.html"][0])
    other = [(e.name, e.description) for s, e in _elements(p, "Accessories") if s == pp.sm.UNKNOWN_SUBCATEGORY]
    assert other == [("Tęczowy proporczyk", "Magiczny dodatek")]


# ── column limits ────────────────────────────────────────────────────────


def _limit(model, column):
    return getattr(model.__table__.c[column].type, "length", None)


def _assert_fits_columns(p):
    comp = models.BikeDetailComponent
    assert len(p.brand) <= _limit(models.Bike, "brand")
    assert len(p.model) <= _limit(models.Bike, "model")
    assert all(len(u) <= _limit(models.BikeDetailPhoto, "url") for u in p.photos)
    for cat in p.components:
        assert len(cat.category) <= _limit(comp, "category")
        for sub in cat.subcategories:
            assert len(sub.subcategory) <= _limit(comp, "subcategory")
            for el in sub.elements:
                assert len(el.name) <= _limit(comp, "element_name")
                if _limit(comp, "element_description") is not None:
                    assert len(el.description) <= _limit(comp, "element_description")
                for s in el.specs:
                    assert len(s.key) <= _limit(comp, "spec_key")
                    assert len(s.value) <= _limit(comp, "spec_value")


@pytest.mark.parametrize("name", CASES)
def test_fixtures_fit_the_model_columns(name):
    _assert_fits_columns(_parse(name))


def test_huge_values_are_cut_to_the_model_columns():
    long = " ".join(["słowo"] * 500)  # 2999 chars
    rows = [("Widelec", long + " x"), ("Materiał ramy", long), ("Coś nowego", long), ("Rozmiar ramy", '19"')]
    p = parse_product(_page(rows, name="Rower MTB KROSS " + long, ld={"image": "https://x.pl/" + "a" * 3000}),
                      BASE + "/x/")
    _assert_fits_columns(p)
    fork = dict(_elements(p, "Frame"))["Fork"]
    assert fork.name.endswith("…") and fork.name[:-1].endswith("słowo")  # cut at a word boundary
    assert p.model.endswith("…")
    assert p.photos == []  # the 3000-char URL does not fit bike_detail_photos.url


def test_fit_helper():
    assert pp.fit("abc", 5) == "abc"
    assert pp.fit("abc", None) == "abc"
    assert pp.fit("alpha beta gamma", 12) == "alpha beta…"
    assert len(pp.fit("x" * 50, 10)) == 10


# ── JSON-LD robustness ───────────────────────────────────────────────────


@pytest.mark.parametrize("ld", [
    {"category": ["Rowery", "Górskie"], "description": {"@value": "Opis."}},
    {"category": 42, "description": 3.5, "image": [{"url": "https://www.centrumrowerowe.pl/photo/a.png"}]},
    {"category": {"name": "Rowery"}, "description": ["Pierwszy opis.", "Drugi."], "image": 7},
    {"description": None, "category": None, "image": None},
])
def test_non_string_json_ld_fields_do_not_crash(ld):
    p = parse_product(_page([("Rozmiar ramy", '19"')], ld=ld), BASE + "/x/")
    assert (p.brand, p.model) == ("Kross", "Level 1.0")


@pytest.mark.parametrize("name, brand", [
    (["Rower MTB KROSS Level 1.0"], "KROSS"),
    ("Rower MTB KROSS Level 1.0", ["KROSS"]),
    ("Rower MTB KROSS Level 1.0", {"@type": "Brand", "name": ["KROSS"]}),
])
def test_list_shaped_name_and_brand(name, brand):
    html = _page([("Rozmiar ramy", '19"')], ld={"name": name, "brand": brand})
    assert parse_product(html, BASE + "/x/").model == "Level 1.0"


def test_numeric_name_is_text_not_a_crash():
    html = _page([("Rozmiar ramy", '19"')], brand="", ld={"name": 12345})
    try:
        assert parse_product(html, BASE + "/x/").raw_name == "12345"
    except ParseError:
        pass  # refusing the page is fine; a TypeError is not


def _ld_page(block):
    rows = '<li><span class="label">Rozmiar ramy</span><span class="value">19"</span></li>'
    return (f'<script type="application/ld+json">{block}</script>'
            f'<div class="section product-spec"><div class="prod-feature"><button class="h3">Rama</button>'
            f'<ul>{rows}</ul></div></div>')


PRODUCT = {"@type": "Product", "name": "Rower MTB KROSS Level 1.0", "brand": "KROSS"}


@pytest.mark.parametrize("block", [
    json.dumps({**PRODUCT, "@type": ["Product", "Thing"]}),
    json.dumps({"@context": "http://schema.org", "@graph": [{"@type": "WebPage"}, PRODUCT]}),
    json.dumps([{"@type": "BreadcrumbList"}, PRODUCT]),
    json.dumps([{"@graph": [PRODUCT]}]),
])
def test_json_ld_wrappers(block):
    assert parse_product(_ld_page(block), BASE + "/x/").model == "Level 1.0"


def test_malformed_json_ld_is_skipped():
    html = ('<script type="application/ld+json">{"@type": "Product", "name": </script>'
            '<script type="application/ld+json"></script>' + _ld_page(json.dumps(PRODUCT)))
    assert parse_product(html, BASE + "/x/").model == "Level 1.0"


def test_photos_keep_only_http_urls():
    ld = {"image": ["javascript:alert(1)", "data:image/png;base64,AAAA", "ftp://x.pl/a.png",
                    "/photo/rel.png", "https://cdn.example.com/b.webp", "//cdn.example.com/c.png"]}
    p = parse_product(_page([("Rozmiar ramy", '19"')], ld=ld), BASE + "/x/")
    assert p.photos == [f"{BASE}/photo/rel.png", "https://cdn.example.com/b.webp", "https://cdn.example.com/c.png"]


def test_to_details_response_is_the_backend_schema():
    p = _parse("mtb_focus_whistler_3_6.html")
    resp = p.to_details_response("FOCUS", "Whistler 3.6")
    assert isinstance(resp, BikeDetailsResponse)
    assert (resp.company, resp.model) == ("FOCUS", "Whistler 3.6")
    assert resp.photos == p.photos
    assert BikeDetailsResponse.model_validate_json(resp.model_dump_json()) == resp


@pytest.mark.parametrize("html", [
    "",
    "<html><body>Nie znaleziono strony</body></html>",
    '<script type="application/ld+json">{"@type": "Product", "name": ""}</script>',
    # Product JSON-LD but no Specyfikacja table.
    '<script type="application/ld+json">{"@type": "Product", "name": "Rower MTB KROSS Level 1.0",'
    ' "brand": {"@type": "Brand", "name": "KROSS"}}</script>',
])
def test_parse_error_on_junk(html):
    with pytest.raises(ParseError):
        parse_product(html, BASE + "/x/")
