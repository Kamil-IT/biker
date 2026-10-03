"""Cover photo of a bike for the result tiles: the first stored photo that is not obvious junk.

The scraped photo lists often start with a map marker, a PDF manual, a logo or a review
thumbnail (a shop's page carries them in front of the gallery). `is_cover_candidate` rejects
those by URL alone — no download — and `get_cover_photos` picks, for many bikes with ONE
query, the first acceptable, non-thumbnail photo (else the first acceptable one) and its stored edge colour (`bike_detail_photos.bg_color`).
The details view's gallery still shows every stored photo; only the tile cover skips junk.
"""
import logging
import re
from typing import Iterable, Optional
from urllib.parse import urlsplit

from .models import BikeDetailPhoto, get_session

logger = logging.getLogger(__name__)

MIGRATION_HINT = "run backend/scripts/migrate_photo_bg_color.py"

_BAD_EXTENSIONS = (".pdf", ".svg", ".ico", ".gif")
# Whole words (delimited by anything that is not a letter or digit, so `Iconic` / `Marketing` stay
# acceptable) ...
_JUNK_WORDS = re.compile(
    r"(?<![a-z0-9])(?:marker|logo|icon|sprite|placeholder|avatar|badge|spinner|loader)s?(?![a-z0-9])"
)
# ... and substrings that are junk wherever they appear (a review widget's host / folder, favicons).
_JUNK_SUBSTRINGS = ("favicon", "judgeme", "judge.me", "review-images", "powered_by")
# Folders of a shop's page chrome, matched in the path only (rowery-indiana.pl's real product
# thumbnails carry `pn=menu-product` in the query, its menu graphics live under /files/menu/).
_JUNK_FOLDERS = ("/menu/",)
# Design-tool exports kept their layer name ("Group-2.png", "Group_459_….png"): brand logos and
# page graphics, not bike photos (Romet Aspre's first stored photo is the Romet logo).
_JUNK_FILENAME = re.compile(r"/group[-_ ]?\d+[^/]*$")


def is_cover_candidate(url: Optional[str]) -> bool:
    """True when `url` can be a bike's cover: http(s), not a PDF / SVG / ICO / GIF, no junk token."""
    if not url:
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return False
    path = parts.path.lower()
    if path.endswith(_BAD_EXTENSIONS) or any(folder in path for folder in _JUNK_FOLDERS):
        return False
    if _JUNK_FILENAME.search(path):
        return False
    text = url.lower()
    if any(token in text for token in _JUNK_SUBSTRINGS):
        return False
    return _JUNK_WORDS.search(text) is None


THUMBNAIL_PX = 400
# Size hints in a URL: cloudinary-style `w_200` / `h_200` (a comma- or slash-separated
# transformation), query `width=` / `w=` / `h=` / `height=`, path pairs `/296_389_crop`,
# `_296x389` / `-150x150.` (WordPress, Shopify).
_SIZE_HINTS = (
    re.compile(r"(?:^|[,/%])[wh]_(\d{1,5})(?=[,/%]|$|\?)"),
    re.compile(r"[?&](?:width|height|w|h)=(\d{1,5})(?=&|$)"),
    re.compile(r"/(\d{2,5})_(\d{2,5})_[a-z]+(?=[./?]|$)"),
    re.compile(r"/(\d{2,5})px-"),
    re.compile(r"[_-](\d{2,5})x(\d{2,5})(?=[._/?]|$)"),
)
_THUMB_FOLDER = re.compile(r"/thumb(?:s|nails?)?/")


def looks_like_thumbnail(url: Optional[str]) -> bool:
    """True when the URL says the image is small: any size hint below 400 px, or - with no size
    hint at all - a `thumbs` / `thumbnails` / `thumb` folder (an explicit big size wins over it,
    e.g. a 1200px Wikimedia thumb)."""
    if not url:
        return False
    text = url.lower()
    sizes = [int(n) for pattern in _SIZE_HINTS for m in pattern.finditer(text) for n in m.groups()]
    if sizes:
        return min(sizes) < THUMBNAIL_PX
    return _THUMB_FOLDER.search(text) is not None


def pick_covers(rows: Iterable[tuple]) -> dict[int, tuple[str, Optional[str]]]:
    """Cover per bike from `(bike_id, url, bg_color)` rows already in display order: the first
    candidate that does not look like a thumbnail, else the first candidate."""
    covers: dict[int, tuple[str, Optional[str]]] = {}
    sized: set[int] = set()
    for bike_id, url, bg_color in rows:
        if bike_id in sized or not is_cover_candidate(url):
            continue
        if not looks_like_thumbnail(url):
            covers[bike_id] = (url, bg_color)
            sized.add(bike_id)
        elif bike_id not in covers:
            covers[bike_id] = (url, bg_color)
    return covers


def _is_unmigrated(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "bg_color" in msg and ("no such column" in msg or "does not exist" in msg)


def get_cover_photos(bike_ids: Iterable[int], session=None) -> dict[int, tuple[str, Optional[str]]]:
    """bike_id -> (cover url, bg_color or None) for the bikes that have a candidate photo.

    ONE query for all ids, `ORDER BY bike_id, display_order, id`; the first candidate per bike
    is picked in Python. Bikes without a candidate are absent. Never raises: a DB error (an
    unmigrated database included) logs at ERROR and yields {} — the tiles then show no photo.
    Pass `session` to reuse the caller's; otherwise one is opened and closed here.
    """
    ids = sorted({i for i in bike_ids if i is not None})
    if not ids:
        return {}
    own = session is None
    if own:
        session = get_session()
    try:
        rows = (
            session.query(BikeDetailPhoto.bike_id, BikeDetailPhoto.url, BikeDetailPhoto.bg_color)
            .filter(BikeDetailPhoto.bike_id.in_(ids))
            .order_by(BikeDetailPhoto.bike_id, BikeDetailPhoto.display_order, BikeDetailPhoto.id)
            .all()
        )
        return pick_covers(rows)
    except Exception as exc:  # noqa: BLE001 — a cosmetic read must never break search / details
        if _is_unmigrated(exc):
            logger.error(
                "cover photos: bike_detail_photos has no bg_color column — database not migrated, %s | %s",
                MIGRATION_HINT, exc,
            )
        else:
            logger.error("cover photos read failed | %s", exc)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {}
    finally:
        if own:
            session.close()
