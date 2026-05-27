import asyncio
import logging
import re
import time
from pathlib import Path

from anthropic import AsyncAnthropic

logger = logging.getLogger("biker.photos")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

# Match img src / data-src with either: explicit image extension OR Cloudinary-style CDN URL
_IMG_SRC = re.compile(
    r'(?:src|data-src)=["\']'
    r'(https?://[^\s"\'<>]+'
    r'(?:\.(?:jpg|jpeg|png|webp)(?:\?[^"\']*)?'   # explicit extension
    r'|/image/upload/[^"\'>]+)'                     # Cloudinary /image/upload/ pattern
    r')["\']',
    re.IGNORECASE,
)
# Reject obvious non-product images
_SKIP = re.compile(
    r"/(?:awards?|logos?|icons?|avatars?|badges?|payments?|flags?|arrows?|spinners?)[/._-]"
    r"|[/_-](?:nav|banner|sale|promo|klarna|paypal|affirm|truemed|logo|icon|badge|award)[_.\-]"
    r"|(?:klarna|paypal|affirm|truemed|logo\.png|logo\.svg)"
    r"|\.gif$"
    r"|/static/.*?/(?:default|icons?)/",
    re.IGNORECASE,
)


async def _find_product_url(company: str, model: str) -> str:
    system_prompt = (PROMPTS_DIR / "bike_photos.md").read_text(encoding="utf-8")
    try:
        response = await _client.messages.create(
            model=MODEL,
            max_tokens=256,
            system=system_prompt,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": f"Find the official product page URL for the {company} {model} bicycle on the manufacturer's website."}],
        )
    except Exception as exc:
        logger.error("photos url-search error | %s", exc)
        return ""

    for block in response.content:
        if getattr(block, "type", None) != "text":
            continue
        for line in block.text.splitlines():
            line = line.strip()
            if line.startswith("http"):
                return line
    return ""


def _scrape_images_sync(url: str) -> list[str]:
    from patchright.sync_api import sync_playwright  # heavy import, deferred

    t = time.perf_counter()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                html = page.content()
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("playwright scrape failed | url=%s error=%s", url, exc)
        return []

    seen: set[str] = set()
    result: list[str] = []
    for raw in _IMG_SRC.findall(html):
        src = raw.strip()
        if not src.startswith("http"):
            continue
        if _SKIP.search(src):
            continue
        if src not in seen:
            seen.add(src)
            result.append(src)
        if len(result) >= 8:
            break

    logger.info(
        "photos scraped | url=%s count=%d elapsed=%.2fs",
        url,
        len(result),
        time.perf_counter() - t,
    )
    return result


async def find_bike_photos(company: str, model: str) -> list[str]:
    product_url = await _find_product_url(company, model)
    if not product_url:
        logger.info("photos: no product URL found for %s %s", company, model)
        return []

    logger.info("photos: scraping %s", product_url)
    try:
        photos = await asyncio.to_thread(_scrape_images_sync, product_url)
    except Exception as exc:
        logger.error("photos scrape error (non-fatal) | %s", exc)
        return []

    return photos
