"""Unit tests for the stored equipment data (TODO-042): app/equipment_repository.py and the
equipment links kept by repository.save_bike_details / emitted by get_bike_details,
each on a fresh temp SQLite database — no server, no network, no AI call.
Run: cd backend && pytest   (collected via pytest.ini)"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import equipment_repository as er, models, repository  # noqa: E402
from app.equipment_models import Equipment, EquipmentDetail, EquipmentDetailComponent, EquipmentDetailPhoto  # noqa: E402
from app.schemas import (  # noqa: E402
    BikeCategory, BikeDescription, BikeDetailsResponse, BikeSubcategory, ComponentElement,
    EquipmentDetailsRequest, EquipmentDetailsResponse, EquipmentPhotosRequest, EquipmentSearchRequest, SpecItem,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(tmp_path / "equipment.db")
    models.init_db()
    yield tmp_path / "equipment.db"
    models.dispose_engine()
    models._db_url = None


def _tree(*elements):
    """[(category, sub, name, [(key, value)…])…] -> BikeCategory list."""
    return [
        BikeCategory(category=c, subcategories=[BikeSubcategory(subcategory=s, elements=[
            ComponentElement(name=n, description="opis", specs=[SpecItem(key=k, value=v) for k, v in specs]),
        ])])
        for c, s, n, specs in elements
    ]


HELMET = "Abus Hyban 2.0"
BIKE_TREE = _tree(
    ("Accessories", "Helmet", HELMET, [("Size", "M")]),
    ("Accessories", "Light", "Lezyne Lite Drive", []),
)
EQUIP_TREE = _tree(("Protection", "Shell", "In-mould shell", [("Weight", "400 g"), ("MIPS", "no")]))


def _bike(brand="Canyon", model="Grizl", tree=BIKE_TREE):
    repository.save_bike_details(brand, model, BikeDetailsResponse(
        company=brand, model=model, description=BikeDescription(text="Rower.", segments=[], citations=[]),
        components=tree,
    ))
    with models.get_session() as s:
        return s.query(models.Bike.id).filter_by(brand=brand, model=model).scalar()


def _equip(text="Kask miejski.", components=EQUIP_TREE, short="Krótko."):
    return EquipmentDetailsResponse(
        company="", model=HELMET, category="helmets",
        description=BikeDescription(text=text, segments=[], citations=[]),
        components=components, short_description=short,
    )


def _links(bike_id):
    with models.get_session() as s:
        return sorted({(r.element_name, r.equipment_id) for r in s.query(models.BikeDetailComponent)
                       .filter_by(bike_id=bike_id)})


def _count(model):
    with models.get_session() as s:
        return s.query(model).count()


def test_save_then_read_by_id_and_by_name(db):
    eid = er.save_equipment_details("", HELMET, "helmets", _equip())
    assert eid is not None
    by_id = er.get_equipment_details(EquipmentDetailsRequest(model="anything", equipment_id=eid))
    assert by_id.equipment_id == eid and by_id.model == HELMET and by_id.category == "helmets"
    assert by_id.description.text == "Kask miejski." and by_id.short_description == "Krótko."
    specs = by_id.components[0].subcategories[0].elements[0].specs
    assert [(s.key, s.value) for s in specs] == [("Weight", "400 g"), ("MIPS", "no")]
    assert by_id.components[0].subcategories[0].elements[0].equipment_id is None

    by_name = er.get_equipment_details(EquipmentDetailsRequest(company=" ", model="  abus HYBAN 2.0 "))
    assert by_name.equipment_id == eid and by_name.description.text == "Kask miejski."


def test_name_lookup_ignores_category_and_takes_the_oldest(db):
    first = er.save_equipment_details("", HELMET, "helmets", _equip())
    second = er.save_equipment_details("", HELMET, "apparel", _equip(text="Inny."))
    assert first != second, "category is part of the save identity"
    got = er.get_equipment_details(EquipmentDetailsRequest(model=HELMET, category="apparel"))
    assert got.equipment_id == first
    assert er.find_equipment_id("", HELMET) == first
    assert er.find_equipment_id("", HELMET, "apparel") == second


def test_unknown_equipment_is_the_empty_response(db):
    got = er.get_equipment_details(EquipmentDetailsRequest(model="Nope", category="locks"))
    assert got.equipment_id is None and got.components == [] and got.description.text == ""
    assert got.category == "locks" and got.short_description == ""
    assert er.get_equipment_details(EquipmentDetailsRequest(model="Nope", equipment_id=999)).equipment_id is None
    assert er.get_equipment_photos(EquipmentPhotosRequest(model="Nope")).photos == []


def test_db_error_is_the_empty_response_and_logs_error(db, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("db down")
    monkeypatch.setattr(er, "_find_equipment_id", boom)
    assert er.get_equipment_details(EquipmentDetailsRequest(model="X")).equipment_id is None
    assert er.get_equipment_photos(EquipmentPhotosRequest(model="X")).photos == []
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_unusable_result_writes_nothing(db):
    bike_id = _bike()
    empty = _equip(text="  ", components=_tree())
    shells = _equip(text="", components=[BikeCategory(category="Protection", subcategories=[])])
    assert er.save_equipment_details("", HELMET, "helmets", empty, bike_id, HELMET) is None
    assert er.save_equipment_details("", HELMET, "helmets", shells, bike_id, HELMET) is None
    assert er.save_equipment_photos("", HELMET, "helmets", [], bike_id, HELMET) == (None, 0)
    assert er.save_equipment_photos("", HELMET, "helmets", ["ftp://x/1.jpg", "/local.png"]) == (None, 0)
    assert _count(Equipment) == 0 and _count(EquipmentDetail) == 0
    assert all(eid is None for _, eid in _links(bike_id))


def test_only_the_produced_half_is_replaced(db):
    eid = er.save_equipment_details("", HELMET, "helmets", _equip())
    er.save_equipment_details("", HELMET, "helmets", _equip(text="Nowy opis.", components=_tree(), short="Nowe."))
    got = er.get_equipment_details(EquipmentDetailsRequest(model=HELMET, equipment_id=eid))
    assert got.description.text == "Nowy opis." and got.short_description == "Nowe."
    assert len(got.components) == 1, "a description-only result keeps the stored components"

    new_tree = _tree(("Protection", "Straps", "Strap", []))
    er.save_equipment_details("", HELMET, "helmets", _equip(text="", components=new_tree))
    got = er.get_equipment_details(EquipmentDetailsRequest(model=HELMET, equipment_id=eid))
    assert got.description.text == "Nowy opis.", "a components-only result keeps the description"
    assert got.components[0].subcategories[0].elements[0].name == "Strap"
    assert got.components[0].subcategories[0].elements[0].specs == []
    assert _count(EquipmentDetail) == 1 and _count(EquipmentDetailComponent) == 1


def test_link_touches_only_that_bike_and_that_element(db):
    grizl = _bike("Canyon", "Grizl")
    other = _bike("Trek", "Marlin")  # same element name on another bike
    eid = er.save_equipment_details("", HELMET, "helmets", _equip(), grizl, " abus hyban 2.0")
    assert _links(grizl) == [(HELMET, eid), ("Lezyne Lite Drive", None)]
    assert _links(other) == [(HELMET, None), ("Lezyne Lite Drive", None)], "never linked globally"
    assert er.link_bike_components(other, HELMET, eid) == 1
    assert _links(other) == [(HELMET, eid), ("Lezyne Lite Drive", None)]
    assert er.link_bike_components(other, "Unknown element", eid) == 0


def test_get_bike_details_emits_equipment_id_and_resave_keeps_it(db):
    bike_id = _bike()
    eid = er.save_equipment_details("", HELMET, "helmets", _equip(), bike_id, HELMET)
    elements = {
        e.name: e.equipment_id
        for c in repository.get_bike_details("canyon", "GRIZL").components
        for s in c.subcategories for e in s.elements
    }
    assert elements == {HELMET: eid, "Lezyne Lite Drive": None}

    # A re-save deletes and re-inserts the component rows: the link follows the element name,
    # an incoming equipment_id (e.g. another database's) is ignored.
    resaved = _tree(
        ("Accessories", "Helmet", HELMET, [("Size", "L"), ("Colour", "black")]),
        ("Accessories", "Light", "Lezyne Lite Drive", []),
    )
    resaved[1].subcategories[0].elements[0].equipment_id = 12345
    _bike(tree=resaved)
    assert _links(bike_id) == [(HELMET, eid), ("Lezyne Lite Drive", None)]


def test_deleting_equipment_unlinks_the_bike_rows(db):
    bike_id = _bike()
    eid = er.save_equipment_details("", HELMET, "helmets", _equip(), bike_id, HELMET)
    with models.get_session() as s:
        s.delete(s.get(Equipment, eid))
        s.commit()
    assert all(link is None for _, link in _links(bike_id)), "ON DELETE SET NULL"
    assert _count(EquipmentDetail) == 0 and _count(EquipmentDetailComponent) == 0


def test_photos_are_insert_only_and_ordered(db):
    bike_id = _bike()
    eid, written = er.save_equipment_photos(
        "", HELMET, "helmets", ["https://a/1.jpg", "http://a/2.jpg", "https://a/" + "x" * 2050], bike_id, HELMET,
    )
    assert written == 2 and eid is not None
    assert (HELMET, eid) in _links(bike_id), "a usable photo result links the element too"
    assert er.save_equipment_photos("", HELMET, "helmets", ["https://b/9.jpg"]) == (eid, 0), "never replaced"
    got = er.get_equipment_photos(EquipmentPhotosRequest(model="x", equipment_id=eid))
    assert got.photos == ["https://a/1.jpg", "http://a/2.jpg"] and got.equipment_id == eid
    assert er.get_equipment_photos(EquipmentPhotosRequest(model=HELMET)).photos == got.photos
    assert _count(EquipmentDetailPhoto) == 2


def test_photos_only_equipment_reads_empty_details_with_its_id(db):
    eid, _ = er.save_equipment_photos("", HELMET, "helmets", ["https://a/1.jpg"])
    got = er.get_equipment_details(EquipmentDetailsRequest(model=HELMET))
    assert got.equipment_id == eid and got.category == "helmets" and got.components == []


def test_request_validation():
    with pytest.raises(ValueError):
        EquipmentSearchRequest(bike_company="Canyon", bike_model="Grizl", element_name="  ")
    with pytest.raises(ValueError):
        EquipmentSearchRequest(bike_company="Canyon", bike_model="Grizl", element_name="x" * 256)
    with pytest.raises(ValueError):
        EquipmentSearchRequest(bike_company="C", bike_model="G", element_name="E", category="x" * 33)
    with pytest.raises(ValueError):
        EquipmentDetailsRequest(model="X", equipment_id=0)
    req = EquipmentSearchRequest(bike_company=" Canyon ", bike_model="Grizl", element_name=" Hyban ", category=" ")
    assert (req.bike_company, req.element_name, req.category) == ("Canyon", "Hyban", None)
