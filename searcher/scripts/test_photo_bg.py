"""Unit tests for the searcher's photo edge colours (bike_detail_photos.bg_color): the bounded
best-effort compute (photo_bg), its SSRF guard, the save with colours (repository.save_photos), the
photos route end to end with stubbed finder + download, and the init_db() column check.
Throwaway SQLite, no CLI run, no network.

Run:
    cd searcher
    python -m pytest scripts/test_photo_bg.py -v
"""
import asyncio
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app import config, models
from app import main as searcher_main
from app import photo_bg
from app.photo_color import edge_color
from app.repository import save_photos

KEY = {"X-Searcher-Key": "secret-key"}


def _png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (30, 20), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    models.dispose_engine()
    models.Base.metadata.create_all(models.get_engine())
    yield
    models.dispose_engine()


def _rows():
    with models.get_engine().connect() as conn:
        return conn.execute(text("SELECT url, display_order, bg_color FROM bike_detail_photos ORDER BY display_order")).all()


def test_compute_colors_in_order_with_failures(monkeypatch):
    images = {"https://a.test/1.png": _png((242, 242, 242, 255)), "https://a.test/t.png": _png((0, 0, 0, 0))}

    def fake_fetch(url, **kw):
        assert kw["url_guard"] is photo_bg.is_public_http_url, "the SSRF guard must be passed on"
        return images.get(url)  # unknown -> None (download failed)

    monkeypatch.setattr(photo_bg, "fetch_image_bytes", fake_fetch)
    urls = ["https://a.test/1.png", "https://a.test/t.png", "https://a.test/missing.png"]
    assert asyncio.run(photo_bg.compute_photo_colors(urls)) == ["#F2F2F2", None, None]
    assert asyncio.run(photo_bg.compute_photo_colors([])) == []


def test_private_hosts_are_never_requested(monkeypatch):
    """The real guard + the real downloader: a private literal is refused before any connection."""
    import httpx

    def boom(*a, **k):
        raise AssertionError("a request was made to a non-public host")

    monkeypatch.setattr(httpx.Client, "stream", boom)
    urls = ["http://127.0.0.1/a.jpg", "http://10.0.0.5/a.jpg", "http://169.254.169.254/latest", "http://localhost/a.jpg"]
    assert asyncio.run(photo_bg.compute_photo_colors(urls)) == [None] * 4


def test_total_budget_is_respected(monkeypatch):
    def slow(url):
        time.sleep(1.5)
        return "#FFFFFF"

    monkeypatch.setattr(photo_bg, "_color_of", slow)

    async def timed():
        t = time.perf_counter()  # measured inside the loop: asyncio.run() itself waits for the sleeping threads
        colors = await photo_bg.compute_photo_colors(["https://a.test/1.png"] * 3, budget=0.2)
        return colors, time.perf_counter() - t

    colors, elapsed = asyncio.run(timed())
    assert colors == [None, None, None]
    assert elapsed < 1.0


def test_save_photos_stores_colors(db):
    bike_id, stored, saved = save_photos("Canyon", "Grizl", ["https://a/1.jpg", "https://a/2.jpg"], ["#F2F2F2", None])
    assert saved == 2 and stored == ["https://a/1.jpg", "https://a/2.jpg"]
    assert _rows() == [("https://a/1.jpg", 0, "#F2F2F2"), ("https://a/2.jpg", 1, None)]


def test_save_photos_without_colors_leaves_null(db):
    save_photos("Canyon", "Grizl", ["https://a/1.jpg", "https://a/2.jpg"])
    assert [r[2] for r in _rows()] == [None, None]
    # a shorter colour list leaves the rest NULL, and a stored set is never replaced
    assert save_photos("Canyon", "Grizl", ["https://b/9.jpg"], ["#000000"])[2] == 0
    assert [r[0] for r in _rows()] == ["https://a/1.jpg", "https://a/2.jpg"]


def test_photos_route_computes_and_stores_colors(db, monkeypatch):
    monkeypatch.setattr(config, "SEARCHER_API_KEY", "secret-key")
    monkeypatch.setattr(searcher_main, "_semaphore", asyncio.Semaphore(2))

    async def finder(company, model):
        return ["https://a.test/1.png", "https://a.test/2.png"], "https://a.test/page"

    images = {"https://a.test/1.png": _png((255, 255, 255, 255))}
    monkeypatch.setattr(searcher_main, "find_bike_photos", finder)
    monkeypatch.setattr(photo_bg, "fetch_image_bytes", lambda url, **kw: images.get(url))
    r = TestClient(searcher_main.app).post("/v1/search/photos", json={"company": "Canyon", "model": "Grizl"}, headers=KEY)
    assert r.status_code == 200, r.text
    assert r.json()["saved"] == 2
    assert [row[2] for row in _rows()] == ["#FFFFFF", None]


def test_photos_route_survives_a_crashing_colour_step(db, monkeypatch):
    monkeypatch.setattr(config, "SEARCHER_API_KEY", "secret-key")
    monkeypatch.setattr(searcher_main, "_semaphore", asyncio.Semaphore(2))

    async def finder(company, model):
        return ["https://a.test/1.png"], "https://a.test/page"

    def explode(url, **kw):
        raise RuntimeError("download blew up")

    monkeypatch.setattr(searcher_main, "find_bike_photos", finder)
    monkeypatch.setattr(photo_bg, "fetch_image_bytes", explode)
    r = TestClient(searcher_main.app).post("/v1/search/photos", json={"company": "Canyon", "model": "Grizl"}, headers=KEY)
    assert r.status_code == 200 and r.json()["saved"] == 1
    assert _rows() == [("https://a.test/1.png", 0, None)]


def test_init_db_requires_bg_color(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'old.db'}")
    models.dispose_engine()
    try:
        models.Base.metadata.create_all(models.get_engine())
        with models.get_engine().begin() as conn:
            conn.execute(text("ALTER TABLE bike_detail_photos DROP COLUMN bg_color"))
        monkeypatch.delenv("SEARCHER_CREATE_TABLES", raising=False)
        with pytest.raises(RuntimeError, match="migrate_photo_bg_color.py"):
            models.init_db()
        with models.get_engine().begin() as conn:
            conn.execute(text("ALTER TABLE bike_detail_photos ADD COLUMN bg_color VARCHAR(7)"))
        models.init_db()  # passes now
    finally:
        models.dispose_engine()


def test_edge_color_is_the_shared_function():
    assert edge_color(_png((10, 20, 30, 255))) == "#0A141E"
