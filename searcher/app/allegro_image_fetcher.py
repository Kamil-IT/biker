"""Allegro offer photos — the backend's old allegro_image_fetcher, moved here (TODO-033).

Same browser fingerprint, same DataDome warm-up on https://allegro.pl and the
same `a.allegroimg.com/(original|s<size>)/…` regex; what changed is the
selection: the old backend kept EVERY match on the page, sorted alphabetically
(49–257 "photos" per offer, recommendation tiles included). This one does what
olx_image_fetcher does — one URL per image, gallery order, ≤ MAX_PHOTOS — and
skips a page that was not served with 200 (a DataDome challenge / 403 carries no
gallery). Nothing here is fatal: a scrape failure returns the offers unchanged,
photos empty, because the offer + price were already paid for by the CLI run.
"""
import asyncio
import logging
import re
import time

from .browser_config import BROWSER_SLOTS, playwright_headless
from .schemas import BikeOffer

logger = logging.getLogger("searcher.allegro_images")

# Every rendition Allegro serves: /original/<id> or /s<size>/<id>, where <id> (the
# path after the rendition segment) is the same for all sizes of one image.
_ALLEGRO_IMG_RE = re.compile(r"https://a\.allegroimg\.com/(?:original|s\d+)/[^\s\"'<>)\\]+")
_RENDITION_RE = re.compile(r"^https://a\.allegroimg\.com/(original|s(\d+))/(.+)$")
_ORIGINAL_RANK = 10**9  # outranks every s<size>
MAX_PHOTOS = 8
WARMUP_URL = "https://allegro.pl"
WARMUP_TIMEOUT_MS = 30000
GOTO_TIMEOUT_MS = 60000  # per offer; ≤ 3 offers stay far inside the backend's 600 s wait
SETTLE_MS = 3000         # after networkidle: the gallery is hydrated client-side


def _extract_images(html: str) -> list[str]:
    """One URL per image, in first-appearance (gallery) order, at most MAX_PHOTOS.

    The page repeats every image in several renditions (src + srcset, JSON
    state), all sharing the path after `/original/` or `/s<size>/`. Group on
    that path, keep the `original` rendition when the page has it and the
    largest `s<size>` otherwise, and keep the order in which the images first
    appear — the gallery comes before the recommendation tiles, which is why
    the cap keeps the offer's own photos rather than other bikes'.
    """
    best: dict[str, tuple[int, str]] = {}  # image id -> (rank, url); dict keeps insertion order
    for u in _ALLEGRO_IMG_RE.findall(html):
        clean = u.replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")
        m = _RENDITION_RE.match(clean)
        if not m:
            continue
        rendition, size, image_id = m.groups()
        rank = _ORIGINAL_RANK if rendition == "original" else int(size)
        if image_id not in best or rank > best[image_id][0]:
            best[image_id] = (rank, clean)
    return [url for _, url in best.values()][:MAX_PHOTOS]


def _fetch_images_sync(urls: list[str]) -> dict[str, list[str]]:
    from patchright.sync_api import sync_playwright  # imported here — heavy import

    results: dict[str, list[str]] = {u: [] for u in urls}
    t = time.perf_counter()

    with BROWSER_SLOTS, sync_playwright() as p:   # slot first: the node driver counts too
        browser = p.chromium.launch(headless=playwright_headless())
        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="pl-PL",
                viewport={"width": 1920, "height": 1080},
            )
            page = context.new_page()
            # Warm up so DataDome issues a valid session cookie before the first offer page.
            page.goto(WARMUP_URL, wait_until="domcontentloaded", timeout=WARMUP_TIMEOUT_MS)
            page.wait_for_timeout(2000)
            logger.info("allegro homepage loaded — DataDome session established")

            for url in urls:
                try:
                    resp = page.goto(url, wait_until="networkidle", timeout=GOTO_TIMEOUT_MS)
                    status = resp.status if resp is not None else None
                    if status != 200:
                        # A DataDome challenge (403) or an expired listing carries no
                        # gallery — scraping it would only yield decoration images.
                        logger.warning("allegro offer page not served | url=%s status=%s", url, status)
                        continue
                    page.wait_for_timeout(SETTLE_MS)
                    html = page.content()
                    images = _extract_images(html)
                    results[url] = images
                    logger.info("allegro images fetched | url=%s status=%s count=%d", url, status, len(images))
                except Exception as exc:
                    logger.warning("allegro image fetch failed | url=%s error=%s", url, exc)
        finally:
            browser.close()

    logger.info("allegro image fetcher done | urls=%d elapsed=%.2fs", len(urls), time.perf_counter() - t)
    return results


async def fetch_images_for_offers(offers: list[BikeOffer]) -> list[BikeOffer]:
    urls = [o.url for o in offers if o.url]
    if not urls:
        return offers

    try:
        url_to_images: dict[str, list[str]] = await asyncio.to_thread(_fetch_images_sync, urls)
    except Exception as exc:
        logger.error("fetch_images_for_offers (allegro) failed (non-fatal) | %s", exc)
        return offers

    return [
        BikeOffer(
            brand=o.brand,
            model=o.model,
            price=o.price,
            is_new=o.is_new,
            url=o.url,
            photos=url_to_images.get(o.url, []),
            source=o.source,
            city=o.city,
        )
        for o in offers
    ]
