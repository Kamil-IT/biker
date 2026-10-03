"""Unit tests for app/photo_cover.py: the URL junk filter and the one-query cover pick, on a
throwaway SQLite file. No server, no network. Run: cd backend && pytest   (collected via pytest.ini)"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models, repository  # noqa: E402
from app.photo_cover import get_cover_photos, is_cover_candidate, looks_like_thumbnail, pick_covers  # noqa: E402
from app.models import Bike, BikeDetailPhoto  # noqa: E402

GOOD = [
    "https://www.canyon.com/media/grizl-cf-7.jpg",
    "http://shop.example/p/1/front.png?v=3",
    "https://cdn.example.com/files/Iconic-Roadster-side.jpg",  # "Iconic" is not the word "icon"
    "https://cdn.example.com/files/marketing-shot.webp",
    "https://cdn.example.com/files/groupset-105-side.jpg",  # only "Group-<number>" exports are junk
    # a real product thumbnail whose query names the shop's menu — only a /menu/ folder is junk
    "https://rowery-indiana.pl/files/thumbs/products/3/opisy/0.jpg/296_389_crop.jpg?ts=1644573284&pn=menu-product",
]
BAD = [
    "https://assets.r-m.de/cms/static/assets/img/retailer-search/maps-marker-default.png",
    "https://bikefriday.com/wp-content/uploads/2021/11/Tikit-Manual-2018.pdf",
    "https://x.test/Manual.PDF?download=1",
    "https://x.test/brand/logo.svg",
    "https://x.test/favicon.ico",
    "https://x.test/anim.gif",
    "https://judgeme.imgix.net/ari-bikes/1762785986__img_0462__original.jpeg?auto=format",
    "https://review-images.judgeme.com/ari-bikes/1763829909__1000027222__original.jpg",
    "https://x.test/assets/Sprite_sheet.png",
    "https://x.test/img/placeholder-bike.jpg",
    "https://x.test/img/avatar_1.jpg",
    "https://x.test/Pashley-saddle-logo.jpg",
    "https://x.test/img/spinner.png",
    "https://rowery-indiana.pl/files/menu/support.jpg",  # a shop's menu graphic, not the bike
    "https://rometbicycles.com/wp-content/uploads/2025/01/Group-2.png",  # design export = the Romet logo
    "https://cdn.shopify.com/s/files/1/0628/3064/1309/files/Group_459_cd8d6129-b7ad-4c36-850f-2720424d3747.png?v=1727889485",
    "https://x.test/img/loader.png",
    "https://x.test/Profile_Badge.png",
    "ftp://x.test/bike.jpg",
    "javascript:alert(1)",
    "/relative/bike.jpg",
    "",
]


@pytest.mark.parametrize("url", GOOD)
def test_good_urls(url):
    assert is_cover_candidate(url)


@pytest.mark.parametrize("url", BAD)
def test_bad_urls(url):
    assert not is_cover_candidate(url)


def test_none_is_not_a_candidate():
    assert not is_cover_candidate(None)


THUMBS = [
    "https://res.cloudinary.com/trekbikes/image/upload/b_rgb:FFFFFF,c_pad,dpr_1.0,f_auto,h_200,q_auto,w_200/c_pad,h_200,w_200/FX3Disc_A?pgw=1",
    "https://x.test/img.jpg?width=150",
    "https://x.test/img.jpg?v=1&w=300&h=200",
    "https://rowery-indiana.pl/files/thumbs/products/3/0.jpg/296_389_crop.jpg?ts=1",
    "https://x.test/wp-content/uploads/bike-150x150.jpg",
    "https://x.test/uploads/bike_296x389.jpg",
    "https://x.test/thumbnails/bike.jpg",
    "https://x.test/thumb/bike.jpg",
]
FULL = [
    "https://res.cloudinary.com/trekbikes/image/upload/f_auto,c_fill,ar_4:3,w_1080,q_auto/Marlin4_A",
    "https://dma.canyon.com/image/upload/w_543,c_fit/b_rgb:F2F2F2/f_auto/q_auto/v1/grizl",
    "https://marinbikes.com/cdn/shop/files/bike.jpg?v=1&width=2000",
    "https://x.test/uploads/bike-1024x768.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8f/Ukraina_W130.jpg/1200px-Ukraina_W130.jpg",
    "https://x.test/files/bike.jpg",
    "",
]


@pytest.mark.parametrize("url", THUMBS)
def test_thumbnail_urls(url):
    assert looks_like_thumbnail(url)


@pytest.mark.parametrize("url", FULL)
def test_full_size_urls(url):
    assert not looks_like_thumbnail(url)


def test_pick_covers_prefers_full_size():
    thumb, thumb2, big = "https://x.test/a.jpg?width=200", "https://x.test/b.jpg?width=100", "https://x.test/c.jpg"
    rows = [
        (1, thumb, "#111111"), (1, big, "#222222"),  # later full-size photo wins
        (2, thumb, None), (2, thumb2, None),  # all thumbnails -> the first candidate
        (3, "https://x.test/logo.svg", None), (3, thumb, None), (3, big, None),  # junk skipped, then thumb < big
    ]
    assert pick_covers(rows) == {1: (big, "#222222"), 2: (thumb, None), 3: (big, None)}


@pytest.fixture()
def db(tmp_path):
    models.configure_db(str(tmp_path / "cover.db"))
    models.init_db()
    yield
    models.configure_db(None)


def _bike(session, brand, photos):
    bike = Bike(brand=brand, model="M")
    session.add(bike)
    session.flush()
    for order, (url, color) in enumerate(photos):
        session.add(BikeDetailPhoto(bike_id=bike.id, url=url, display_order=order, bg_color=color))
    return bike.id


def test_get_cover_photos(db):
    s = models.get_session()
    a = _bike(s, "A", [("https://x.test/logo.svg", None), ("https://x.test/a.jpg", "#F2F2F2"), ("https://x.test/a2.jpg", "#000000")])
    b = _bike(s, "B", [("https://x.test/maps-marker.png", None), ("https://x.test/doc.pdf", None)])  # all junk
    c = _bike(s, "C", [])
    d = _bike(s, "D", [("https://x.test/d.jpg", None)])
    s.commit()
    s.close()
    covers = get_cover_photos([a, b, c, d, 999999, None])
    assert covers == {a: ("https://x.test/a.jpg", "#F2F2F2"), d: ("https://x.test/d.jpg", None)}


def test_display_order_beats_id(db):
    s = models.get_session()
    bike = Bike(brand="O", model="M")
    s.add(bike)
    s.flush()
    s.add(BikeDetailPhoto(bike_id=bike.id, url="https://x.test/second.jpg", display_order=1))
    s.add(BikeDetailPhoto(bike_id=bike.id, url="https://x.test/first.jpg", display_order=0, bg_color="#FFFFFF"))
    s.commit()
    bid = bike.id
    s.close()
    assert get_cover_photos([bid]) == {bid: ("https://x.test/first.jpg", "#FFFFFF")}


def test_empty_input_runs_no_query():
    assert get_cover_photos([]) == {}


def test_one_query_for_many_bikes(db):
    s = models.get_session()
    ids = [_bike(s, f"B{i}", [("https://x.test/a.jpg", None)]) for i in range(5)]
    s.commit()
    s.close()
    from sqlalchemy import event
    engine = models.get_engine()
    seen = []

    def listener(conn, cursor, statement, *rest):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        assert len(get_cover_photos(ids)) == 5
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert sum("bike_detail_photos" in q for q in seen) == 1


def test_results_carry_the_cover(db):
    s = models.get_session()
    a = _bike(s, "Aaa", [("https://x.test/logo.svg", None), ("https://x.test/a.jpg", "#F2F2F2")])
    e = _bike(s, "Eee", [])
    s.commit()
    s.close()
    by_id = repository.get_bike_by_id(a)
    assert (by_id.photo, by_id.photo_bg) == ("https://x.test/a.jpg", "#F2F2F2")
    assert repository.get_bike_by_id(e).photo is None
    assert repository.get_bike_by_id(e).photo_bg is None


def test_backfill_targets_and_local_guard():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backfill_photo_bg_color import is_local, select_targets
    rows = [
        (1, 10, "https://x.test/logo.svg", None),  # junk: skipped
        (2, 10, "https://x.test/a.jpg", None),  # bike 10's cover, no colour -> target
        (3, 10, "https://x.test/a2.jpg", None),  # not the cover
        (4, 11, "https://x.test/b.jpg", "#FFFFFF"),  # cover already coloured -> done
        (5, 11, "https://x.test/b2.jpg", None),  # not the cover
    ]
    assert select_targets(rows, all_photos=False) == [(2, 10, "https://x.test/a.jpg")]
    assert [t[0] for t in select_targets(rows, all_photos=True)] == [2, 3, 5]
    assert is_local("sqlite:///x.db")
    assert is_local("postgresql+psycopg://u@localhost:5432/d")
    assert is_local("postgresql+psycopg://u@127.0.0.1:5433/d")
    assert not is_local("postgresql+psycopg://u@127.0.0.1:6543/d")
    assert not is_local("postgresql+psycopg://u@10.1.2.3:5432/d")
    assert not is_local("postgresql+psycopg://u@/d?host=/cloudsql/p:r:i")


def test_unmigrated_database_degrades_to_no_photo(db, caplog):
    from sqlalchemy import text
    s = models.get_session()
    a = _bike(s, "Old", [("https://x.test/a.jpg", None)])
    s.commit()
    s.close()
    with models.get_engine().begin() as conn:
        conn.execute(text("ALTER TABLE bike_detail_photos DROP COLUMN bg_color"))
    with caplog.at_level("ERROR"):
        assert get_cover_photos([a]) == {}
    assert "migrate_photo_bg_color.py" in caplog.text
    # the answer built on top still works, just without a photo
    assert repository.get_bike_by_id(a).photo is None
