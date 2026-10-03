"""Edge colours for the photos the searcher is about to store (bike_detail_photos.bg_color).

Best-effort and bounded: each image is downloaded only when its URL (and every redirect hop)
passes the public-address guard `photos_finder.is_public_http_url`, the colour is computed by
`photo_color.edge_color`, and the whole batch has a time budget. A photo whose colour is
missing for any reason (blocked host, download failed, transparent, too slow) gets None and is
stored all the same — the colour is cosmetic and must never fail or hold up the save.
"""
import asyncio
import logging
from typing import Optional

from .photo_color import edge_color, fetch_image_bytes
from .photos_finder import is_public_http_url

logger = logging.getLogger(__name__)

TOTAL_BUDGET_SECONDS = 20.0
PER_IMAGE_TIMEOUT = 8.0
MAX_CONCURRENT = 4


def _color_of(url: str) -> Optional[str]:
    """Blocking: download one image behind the SSRF guard and compute its colour; None on any failure."""
    data = fetch_image_bytes(url, timeout=PER_IMAGE_TIMEOUT, url_guard=is_public_http_url)
    return edge_color(data) if data else None


async def compute_photo_colors(urls: list[str], budget: float = TOTAL_BUDGET_SECONDS) -> list[Optional[str]]:
    """One colour (or None) per URL, in order; never raises, returns within about `budget` seconds."""
    if not urls:
        return []
    gate = asyncio.Semaphore(MAX_CONCURRENT)

    async def one(url: str) -> Optional[str]:
        async with gate:
            try:
                return await asyncio.to_thread(_color_of, url)
            except Exception as exc:  # noqa: BLE001 — cosmetic
                logger.info("photo colour failed | url=%r | %s", url, exc)
                return None

    tasks = [asyncio.ensure_future(one(u)) for u in urls]
    try:
        await asyncio.wait(tasks, timeout=budget)
    except Exception as exc:  # noqa: BLE001
        logger.warning("photo colours: wait failed | %s", exc)
    colors: list[Optional[str]] = []
    for task in tasks:
        if task.done() and not task.cancelled() and task.exception() is None:
            colors.append(task.result())
        else:
            task.cancel()
            colors.append(None)
    logger.info("photo colours | photos=%d coloured=%d", len(urls), sum(c is not None for c in colors))
    return colors
