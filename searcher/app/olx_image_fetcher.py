import asyncio
import logging
import re
import time

from .browser_config import playwright_headless
from .schemas import BikeOffer

logger = logging.getLogger("searcher.olx_images")

# OLX now writes its CDN links with an explicit port ("…olxcdn.com:443/v1/files/…"),
# which the original "\.com/" pattern silently missed — every listing came back with
# zero photos while the page itself was fine.
_OLX_IMG_RE = re.compile(r"https://[a-z0-9\-]+\.apollo\.olxcdn\.com(?::\d+)?/[^\s\"'<>),\\]+")
_SIZE_RE = re.compile(r";s=(\d+)x(\d+)")
GOTO_TIMEOUT_MS = 20000  # per listing; 5 listings must stay far inside the backend's 600 s wait


def _extract_images(html: str) -> list[str]:
    """One URL per photo, in gallery order.

    The page repeats every photo in several sizes (src + srcset), all sharing
    the same `/v1/files/<id>/image` path. Group on that path, keep the largest
    rendition (a plain path without `;s=` counts as the original), and keep
    the order in which the photos first appear — the gallery order.
    """
    best: dict[str, tuple[int, str]] = {}  # file path -> (area, url); dict keeps insertion order
    for u in _OLX_IMG_RE.findall(html):
        clean = u.replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&").replace(":443/", "/")
        key = clean.split(";s=")[0]
        m = _SIZE_RE.search(clean)
        area = int(m.group(1)) * int(m.group(2)) if m else 10**9
        if key not in best or area > best[key][0]:
            best[key] = (area, clean)
    return [url for _, url in best.values()]


def _fetch_images_sync(urls: list[str]) -> dict[str, list[str]]:
    from patchright.sync_api import sync_playwright  # imported here — heavy import

    results: dict[str, list[str]] = {u: [] for u in urls}
    t = time.perf_counter()

    with sync_playwright() as p:
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

            for url in urls:
                try:
                    # 20 s per listing keeps the worst case (5 listings) well inside the
                    # backend's SEARCHER_TIMEOUT even after a 300 s CLI run.
                    resp = page.goto(url, wait_until="networkidle", timeout=GOTO_TIMEOUT_MS)
                    status = resp.status if resp is not None else None
                    if status != 200:
                        # OLX answers 503 "Ups! Coś poszło nie tak" when it rate-limits an
                        # IP — the page carries no listing images, so do not scrape it.
                        logger.warning("olx listing page not served | url=%s status=%s", url, status)
                        continue
                    page.wait_for_timeout(2000)
                    html = page.content()
                    images = _extract_images(html)[:4]
                    results[url] = images
                    logger.info("olx images fetched | url=%s count=%d", url, len(images))
                except Exception as exc:
                    logger.warning("olx image fetch failed | url=%s error=%s", url, exc)
        finally:
            browser.close()

    logger.info("olx image fetcher done | urls=%d elapsed=%.2fs", len(urls), time.perf_counter() - t)
    return results


async def fetch_images_for_offers(offers: list[BikeOffer]) -> list[BikeOffer]:
    urls = [o.url for o in offers if o.url]
    if not urls:
        return offers

    try:
        url_to_images: dict[str, list[str]] = await asyncio.to_thread(_fetch_images_sync, urls)
    except Exception as exc:
        logger.error("fetch_images_for_offers (olx) failed (non-fatal) | %s", exc)
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
