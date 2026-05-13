import asyncio
import logging
import re
import time

from .schemas import BikeOffer

logger = logging.getLogger("biker.images")

_ALLEGRO_IMG_RE = re.compile(r"https://a\.allegroimg\.com/(?:original|s\d+)/[^\s\"'<>)\\]+")


def _extract_images(html: str) -> list[str]:
    urls: set[str] = set()
    for u in _ALLEGRO_IMG_RE.findall(html):
        clean = u.replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")
        urls.add(clean)
    return sorted(urls)


def _fetch_images_sync(urls: list[str]) -> dict[str, list[str]]:
    from patchright.sync_api import sync_playwright  # imported here — heavy import

    results: dict[str, list[str]] = {u: [] for u in urls}
    t = time.perf_counter()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
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
            # Warm up so DataDome issues a valid session cookie
            page.goto("https://allegro.pl", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            logger.info("allegro homepage loaded — DataDome session established")

            for url in urls:
                try:
                    page.goto(url, wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(3000)
                    html = page.content()
                    images = _extract_images(html)
                    results[url] = images
                    logger.info("images fetched | url=%s count=%d", url, len(images))
                except Exception as exc:
                    logger.warning("image fetch failed | url=%s error=%s", url, exc)
        finally:
            browser.close()

    logger.info("image fetcher done | urls=%d elapsed=%.2fs", len(urls), time.perf_counter() - t)
    return results


async def fetch_images_for_offers(offers: list[BikeOffer]) -> list[BikeOffer]:
    urls = [o.url for o in offers if o.url]
    if not urls:
        return offers

    try:
        url_to_images: dict[str, list[str]] = await asyncio.to_thread(_fetch_images_sync, urls)
    except Exception as exc:
        logger.error("fetch_images_for_offers failed (non-fatal) | %s", exc)
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
        )
        for o in offers
    ]
