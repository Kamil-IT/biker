"""The edge colour of a photo — the background of the results tile's `object-fit: contain` frame.

`edge_color(bytes)` samples small patches at the four corners and returns the per-channel
median as "#RRGGBB" (upper-case), or None when the colour cannot be trusted (transparent
corners, undecodable data, a decompression bomb). `fetch_image_bytes(url)` downloads an image
with a size cap. Both never raise — any failure is None, because the colour is cosmetic.

The searcher carries a verbatim copy of this file (searcher/app/photo_color.py) — change the
backend's first, then the copy.
"""
import io
import logging
import statistics
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 50_000_000  # decompression-bomb guard: Pillow warns above, errors above 2x
PATCH_FRACTION = 0.03  # corner patch edge = 3 % of the shorter side ...
PATCH_MIN_PX = 2  # ... but at least this many pixels
OPAQUE_ALPHA = 250  # a corner pixel below this is "meaningfully transparent"
MAX_REDIRECTS = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


def edge_color(data: bytes) -> Optional[str]:
    """"#RRGGBB" of the image's corner colour, or None (transparent corners / not an image / too big)."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.draft("RGB", (256, 256))  # JPEG: decode at reduced size, cheap
            rgba = img.convert("RGBA")
        width, height = rgba.size
        if width < 1 or height < 1:
            return None
        patch = max(PATCH_MIN_PX, round(min(width, height) * PATCH_FRACTION))
        patch = min(patch, width, height)
        boxes = (
            (0, 0), (width - patch, 0), (0, height - patch), (width - patch, height - patch),
        )
        channels: list[list[int]] = [[], [], []]
        for left, top in boxes:
            raw = rgba.crop((left, top, left + patch, top + patch)).tobytes()  # RGBA, 4 bytes a pixel
            for r, g, b, a in zip(raw[0::4], raw[1::4], raw[2::4], raw[3::4]):
                if a < OPAQUE_ALPHA:
                    return None
                channels[0].append(r)
                channels[1].append(g)
                channels[2].append(b)
        r, g, b = (int(round(statistics.median(c))) for c in channels)
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception as exc:  # noqa: BLE001 — cosmetic: never break the caller
        logger.info("edge_color failed (%s) | %s", type(exc).__name__, exc)
        return None


def fetch_image_bytes(
    url: str, *, max_bytes: int = 8_000_000, timeout: float = 15,
    url_guard: Optional[Callable[[str], bool]] = None,
) -> Optional[bytes]:
    """The body of an http(s) `url` (≤ `max_bytes`, ≤ 3 redirects), or None on any failure.

    `url_guard(url) -> bool`, when given, must approve the first URL and every redirect hop
    (the searcher passes its public-address check, so a redirect cannot lead to a private host).
    Redirects are followed by hand for that reason.
    """
    try:
        current = url
        with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if urlsplit(current).scheme not in ("http", "https"):
                    return None
                if url_guard is not None and not url_guard(current):
                    return None
                with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    if resp.status_code != 200:
                        return None
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        return None
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            return None
                        chunks.append(chunk)
                    return b"".join(chunks)
        return None  # too many redirects
    except Exception as exc:  # noqa: BLE001
        logger.info("fetch_image_bytes failed (%s) | url=%r | %s", type(exc).__name__, url, exc)
        return None
