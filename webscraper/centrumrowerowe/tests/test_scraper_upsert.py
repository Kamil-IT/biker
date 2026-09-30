import scrape_rowery as sr

ROWS = [
    {"name": "Rower trekkingowy ROMET Wagant 3", "price": "2199.00",
     "url": "https://www.centrumrowerowe.pl/rower-trekkingowy-romet-wagant-3-pd27404/?v_Id=1"},
    {"name": "Rower trekkingowy ROMET Wagant 3", "price": "1999.00",
     "url": "https://www.centrumrowerowe.pl/rower-trekkingowy-romet-wagant-3-pd27404/?v_Id=2"},
    {"name": "Rower MTB KROSS Level X300", "price": "3500.00",
     "url": "https://www.centrumrowerowe.pl/rower-mtb-kross-level-x300-pd57104/"},
    {"name": "No id", "price": "1", "url": "https://www.centrumrowerowe.pl/inne/"},
]


def _listings(db):
    with db.session() as s:
        return {r.source_product_id: r for r in s.query(db.BikeDiscoveryListing) if not s.expunge(r)}


def _bikes(db):
    with db.session() as s:
        return {(r.company_norm, r.model_norm): r for r in s.query(db.BikeDiscovery) if not s.expunge(r)}


def test_grouping():
    items = {i["source_product_id"]: i for i in sr.group_products(ROWS)}
    assert set(items) == {"pd27404", "pd57104"}
    wagant = items["pd27404"]
    assert wagant["price"] == "1999.00"
    assert wagant["details_link"].endswith("-pd27404/") and "v_Id" not in wagant["details_link"]
    assert wagant["variant_ids"] == ["1", "2"]
    assert (wagant["bike_type"], wagant["company"], wagant["model"]) == ("trekkingowy", "ROMET", "Wagant 3")


def test_upsert_twice_inserts_nothing_and_keeps_state(temp_db):
    db = temp_db
    items = sr.group_products(ROWS)
    assert sr.upsert(items) == (2, 2, 0)
    bikes = _bikes(db)
    assert set(bikes) == {("romet", "wagant 3"), ("kross", "level x300")}
    assert _listings(db)["pd27404"].discovery_id == bikes[("romet", "wagant 3")].id

    with db.session() as s:  # simulate the worker having processed the bike (and corrected its name)
        bike = db.models.Bike(brand="Romet", model="Wagant 3")
        s.add(bike)
        s.flush()
        row = s.query(db.BikeDiscovery).filter_by(company_norm="romet").one()
        row.status, row.attempts, row.bike_id, row.company = db.DONE, 2, bike.id, "Romet"
        bike_id = bike.id
        s.commit()

    assert sr.upsert(items) == (0, 0, 2)
    changed = sr.group_products([{**ROWS[0], "name": "Rower trekkingowy ROMET Wagant 3 NEW", "price": "1500.00"}])
    assert sr.upsert(changed) == (0, 0, 1)

    bikes, listings = _bikes(db), _listings(db)
    assert len(bikes) == 2 and len(listings) == 2
    wagant = bikes[("romet", "wagant 3")]
    assert (wagant.status, wagant.attempts, wagant.bike_id, wagant.company) == (db.DONE, 2, bike_id, "Romet")
    listing = listings["pd27404"]
    assert listing.raw_name.endswith("NEW") and listing.price == "1500.00"
    assert listing.discovery_id == wagant.id  # a known listing never changes bike
    kross = bikes[("kross", "level x300")]
    assert kross.status == db.PENDING and kross.attempts == 0


def test_second_product_with_same_name_joins_the_bike(temp_db):
    db = temp_db
    sr.upsert(sr.group_products(ROWS))
    with db.session() as s:
        row = s.query(db.BikeDiscovery).filter_by(company_norm="romet").one()
        row.status, row.attempts = db.FAILED, 1
        s.commit()
    other = {"name": "Rower trekkingowy Romet WAGANT 3", "price": "1800.00",
             "url": "https://www.centrumrowerowe.pl/rower-trekkingowy-romet-wagant-3-pd99999/"}
    assert sr.upsert(sr.group_products([other])) == (0, 1, 0)
    bikes, listings = _bikes(db), _listings(db)
    wagant = bikes[("romet", "wagant 3")]
    assert listings["pd99999"].discovery_id == listings["pd27404"].discovery_id == wagant.id
    assert (wagant.company, wagant.status, wagant.attempts) == ("ROMET", db.FAILED, 1)  # bike untouched


def test_off_host_and_bad_urls_rejected():
    rows = [
        {"name": "Rower MTB KROSS A", "price": "1", "url": "https://evil.example/rower-a-pd1/"},
        {"name": "Rower MTB KROSS B", "price": "1", "url": "http://www.centrumrowerowe.pl/rower-b-pd2/"},
        {"name": "Rower MTB KROSS C", "price": "1", "url": "https://www.centrumrowerowe.pl.evil.example/rower-c-pd3/"},
        {"name": "Rower MTB KROSS D", "price": "1", "url": "https://www.centrumrowerowe.pl/rower-d/"},
        {"name": "Rower MTB KROSS E", "price": "1", "url": "https://centrumrowerowe.pl/rower-e-pd5/"},
        {"name": "Rower MTB KROSS F", "price": "1", "url": "https://www.centrumrowerowe.pl/" + "x" * 2100 + "-pd6/"},
    ]
    stats = {}
    items = sr.group_products(rows, stats)
    assert [i["source_product_id"] for i in items] == ["pd5"]
    assert stats["skipped"] == 5


def _ld(obj):
    import json
    return '<script type="application/ld+json">' + json.dumps(obj) + "</script>"


def _item(name, url, price="10.00"):
    return {"item": {"name": name, "url": url, "offers": {"price": price}}}


def test_products_survives_malformed_blocks():
    good = {"@type": "ItemList", "itemListElement": [
        _item("A", "https://www.centrumrowerowe.pl/a-pd1/"),
        {"item": {"name": "no url"}},          # missing url
        {"nope": 1},                            # missing item
        "junk",
        _item("B", "https://www.centrumrowerowe.pl/b-pd2/"),
    ]}
    html = "".join([
        '<script type="application/ld+json">{broken</script>',
        _ld([{"@type": "Organization"}, good]),                          # top-level list
        _ld({"@graph": [{"@type": "ItemList", "itemListElement": [_item("C", "https://www.centrumrowerowe.pl/c-pd3/")]}]}),
        _ld({"@type": "ItemList", "itemListElement": "not a list"}),
        _ld("just a string"),
    ])
    assert [p["name"] for p in sr.products(html)] == ["A", "B", "C"]
