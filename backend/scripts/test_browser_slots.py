"""Unit tests for app/browser_config.py BROWSER_SLOTS: no scraper may hold more than
BROWSER_MAX_CONCURRENCY browser launches at once, and a slot is always given back.
Playwright is replaced by a fake, so no browser starts and no network is touched.
Run: cd backend && pytest   (collected via pytest.ini)"""
import os
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-never-used")   # the finders build a client at import

from app import allegro_image_fetcher, bike_photos_finder, browser_config, equipment_photos_finder, olx_image_fetcher  # noqa: E402


class _Gauge:
    """Counts fake browsers alive at the same time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.fail = False

    def enter(self):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def leave(self):
        with self.lock:
            self.active -= 1


def _fake_sync_playwright(gauge: _Gauge, hold: float = 0.15):
    class _Page:
        def goto(self, *a, **k):
            if gauge.fail:
                raise RuntimeError("boom")
            time.sleep(hold)

        def wait_for_timeout(self, *a, **k):
            pass

        def content(self):
            return "<html></html>"

    class _Context:
        def new_page(self):
            return _Page()

    class _Browser:
        def new_context(self, **k):
            return _Context()

        def close(self):
            pass

    class _Chromium:
        def launch(self, **k):
            return _Browser()

    class _Playwright:
        chromium = _Chromium()

    class _Manager:
        def __enter__(self):
            gauge.enter()
            return _Playwright()

        def __exit__(self, *exc):
            gauge.leave()
            return False

    return lambda: _Manager()


@pytest.fixture
def fake_playwright(monkeypatch):
    gauge = _Gauge()
    sync_api = types.ModuleType("patchright.sync_api")
    sync_api.sync_playwright = _fake_sync_playwright(gauge)
    pkg = types.ModuleType("patchright")
    pkg.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "patchright", pkg)          # scrapers import it lazily, per call
    monkeypatch.setitem(sys.modules, "patchright.sync_api", sync_api)
    return gauge


SCRAPERS = [
    pytest.param(lambda: olx_image_fetcher._fetch_images_sync(["https://www.olx.pl/x"]), id="olx"),
    pytest.param(lambda: allegro_image_fetcher._fetch_images_sync(["https://allegro.pl/x"]), id="allegro"),
    pytest.param(lambda: bike_photos_finder._scrape_images_sync("https://www.trekbikes.com/x"), id="bike-photos"),
    pytest.param(lambda: equipment_photos_finder._scrape_images_sync("https://www.pocsports.com/x"), id="equipment-photos"),
]


@pytest.mark.parametrize("scrape", SCRAPERS)
def test_scraper_never_exceeds_browser_slots(fake_playwright, scrape):
    limit = browser_config.BROWSER_MAX_CONCURRENCY
    workers = limit * 4
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda _: scrape(), range(workers)))
    assert fake_playwright.peak == limit, "browsers must overlap up to the cap, and never beyond it"
    assert fake_playwright.active == 0, "every slot must be released"


def test_slot_released_when_scrape_raises(fake_playwright):
    fake_playwright.fail = True
    with pytest.raises(RuntimeError):
        allegro_image_fetcher._fetch_images_sync(["https://allegro.pl/x"])   # warm-up goto raises outside the inner try
    sem = browser_config.BROWSER_SLOTS
    taken = [sem.acquire(blocking=False) for _ in range(browser_config.BROWSER_MAX_CONCURRENCY)]
    try:
        assert all(taken), "the failed scrape must not keep its slot"
    finally:
        for ok in taken:
            if ok:
                sem.release()


@pytest.mark.parametrize("raw,expected", [(None, 2), ("2", 2), ("3", 3), ("0", 1), ("-4", 1), ("abc", 2), (" 1 ", 1)])
def test_browser_max_concurrency_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("BROWSER_MAX_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("BROWSER_MAX_CONCURRENCY", raw)
    assert browser_config.browser_max_concurrency() == expected
