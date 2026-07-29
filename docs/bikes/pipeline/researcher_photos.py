"""Researcher 2 — bike_detail_photos (port 9103).

Mirrors app/bike_photos_finder.py: step 1 finds the manufacturer product page,
step 2 scrapes up to 8 product <img> URLs from the rendered page with the same
_IMG_SRC / _SKIP regexes. Step 2 is fully deterministic so this service does it
itself; only step 1 needs a model, and that is handed to an agent as a work
order (subscription tokens, no API key).

Run:  .venv/Scripts/python.exe -m uvicorn pipeline.researcher_photos:app --port 9103
"""
import hashlib
import logging
import time

from fastapi import FastAPI
from pydantic import BaseModel

from pipeline.common import PROMPTS_DIR
from pipeline.photo_extract import (
    _UA,
    _SKIP,
    _dedupe_key,
    _relevance,
    extract_images,
    shopify_images,
    verify,
)

# fingerprint -> "brand|model" of the first product that returned that exact set
_SEEN_SETS: dict[str, str] = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("pipeline.researcher_photos")

app = FastAPI(title="researcher-photos")


class ScrapeRequest(BaseModel):
    brand: str
    model: str
    product_url: str


def _url_alive(url: str) -> bool:
    """Cheap pre-check. Round 1 spent a full browser launch on a 404 product page."""
    import httpx

    # Round 4: bare httpx was refused on the first request and served on an
    # immediate identical retry, which read as a dead product URL and cost four
    # wasted round-trips. A real UA plus one retry fixes it.
    for attempt in (1, 2):
        try:
            with httpx.Client(timeout=20, follow_redirects=True, headers=_UA) as c:
                r = c.get(url)
                if r.status_code < 400:
                    return True
                logger.warning("url pre-check %s | attempt %d | %s", r.status_code, attempt, url)
        except Exception as exc:
            logger.warning("url pre-check failed | attempt %d | url=%s error=%s", attempt, url, exc)
        time.sleep(1)
    return False


def _authoritative_images(url: str, brand: str, model: str) -> tuple[list[str], str, list[dict]]:
    """Shopify declares each product's own gallery — no inference needed.

    Round 4: every other strategy is guesswork next to this. Chromag's plain
    `Minor Threat` page yielded 7 of 8 images belonging to `Minor Threat V2`
    while reporting 8/8 filename-matched. This endpoint is per-product and
    authoritative, and needs no browser launch at all.
    """
    urls, title = shopify_images(url)
    if not urls:
        return [], "", []

    rejects: list[dict] = []
    seen: set[str] = set()
    kept: list[str] = []
    for u in urls:
        if _SKIP.search(u):
            rejects.append({"url": u, "reason": "skip-pattern (site chrome in product gallery)"})
            continue
        # NO sibling/variant filtering here, deliberately. This gallery is the
        # product's own declaration, so there is nothing left to infer and the
        # filter can only subtract truth: in round 5 it rejected
        # `chromag-bikes-primer-20th_anniversary-...jpg` — a real Primer
        # colourway — from the Primer's own gallery. Filename inference stays
        # where it is still needed: the render fallback.
        k = _dedupe_key(u)
        if k in seen:
            rejects.append({"url": u, "reason": "duplicate render of an image already kept"})
            continue
        seen.add(k)
        kept.append(u)

    logger.info("authoritative gallery | %s %s | title=%r | %d images",
                brand, model, title, len(kept))
    return kept, "shopify-images", rejects


def _scrape_images_sync(url: str, brand: str = "", model: str = "") -> tuple[list[str], str, list[dict]]:
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
                # A flat 4s missed JS galleries in round 1. Settle the network,
                # then scroll to trip intersection-observer lazy loading.
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1500)
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1500)
                html = page.content()
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("playwright scrape failed | url=%s error=%s", url, exc)
        return [], "error", []

    urls, source, rejects = extract_images(
        html, base_url=url, limit=12, brand=brand, model=model
    )
    verified = verify(urls)
    for u in urls:
        if u not in verified:
            rejects.append({"url": u, "reason": "HEAD verify failed (non-200 or <15KB)"})
    urls = verified[:8]

    logger.info("photos scraped | url=%s count=%d source=%s rejects=%d elapsed=%.2fs",
                url, len(urls), source, len(rejects), time.perf_counter() - t)
    return urls, source, rejects


@app.get("/health")
def health() -> dict:
    return {"service": "researcher_photos"}


@app.get("/task")
def task(brand: str, model: str) -> dict:
    """Work order: find the manufacturer product page URL. That is the only LLM step."""
    prompt_file = PROMPTS_DIR / "bike_photos.md"
    return {
        "brand": brand,
        "model": model,
        "system_prompt_file": str(prompt_file),
        "system_prompt": prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "",
        "user_message": (
            f"Find the official product page URL for the {brand} {model} bicycle "
            "on the manufacturer's website."
        ),
        "instructions": (
            "Return ONLY the product page URL. Post it to /scrape and this service will "
            "render the page and extract the product images itself — do not collect or "
            "invent image URLs yourself. If no official product page exists, post an "
            "empty product_url and photos will be []."
        ),
        "submit_to": "/scrape",
    }


@app.post("/scrape")
def scrape(req: ScrapeRequest) -> dict:
    if not req.product_url:
        logger.info("no product URL for %s %s", req.brand, req.model)
        return {"ok": True, "payload": {"photos": [], "source_urls": []}, "note": "no product url"}

    if not _url_alive(req.product_url):
        logger.warning("product url dead | %s %s | %s", req.brand, req.model, req.product_url)
        return {
            "ok": True,
            "payload": {"photos": [], "source_urls": []},
            "note": "product url returned >=400 — stale search result, no browser launched",
        }

    # Authoritative first: one cheap request, per-product, no browser, no
    # inference. Only fall back to rendering when the site is not Shopify.
    photos, source, rejects = _authoritative_images(req.product_url, req.brand, req.model)
    if photos:
        photos = verify(photos)[:8]
    else:
        photos, source, rejects = _scrape_images_sync(req.product_url, req.brand, req.model)

    # Cross-page identity check. Round 2: two different Aventon models returned
    # byte-identical 8-URL lists of site chrome and both reported success. An
    # identical set across two products means the set belongs to the site, not
    # the bike.
    warning = None
    fingerprint = hashlib.sha1("|".join(sorted(photos)).encode()).hexdigest() if photos else ""
    if fingerprint:
        prev = _SEEN_SETS.get(fingerprint)
        if prev and prev != f"{req.brand}|{req.model}":
            warning = (
                f"identical image set already returned for {prev} — this is site chrome, "
                "not this bike's gallery. Photos suppressed."
            )
            logger.warning("duplicate image set | %s %s == %s", req.brand, req.model, prev)
            rejects.extend({"url": u, "reason": "duplicate set across products"} for u in photos)
            photos = []
        else:
            _SEEN_SETS[fingerprint] = f"{req.brand}|{req.model}"

    matched = sum(1 for u in photos if _relevance(u, req.brand, req.model) > 0)
    return {
        "ok": True,
        "payload": {"photos": photos, "source_urls": [req.product_url] if photos else []},
        "note": (f"extracted via {source}, HEAD-verified"
                 + (" (authoritative product gallery)" if source == "shopify-images"
                    else f", {matched}/{len(photos)} filename-matched [advisory only]")),
        "warning": warning,
        "rejects": rejects[:20],
    }
