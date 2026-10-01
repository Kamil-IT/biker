"""Bike photo search — the backend's old bike_photos_finder, moved here.

Two steps, as before: (1) find the official manufacturer product page, (2)
Playwright opens it once and takes up to 8 product <img> URLs. Step 2 is the
backend's scrape unchanged (same _IMG_SRC / _SKIP regexes, max 8,
domcontentloaded + 4 s, same user agent and viewport, patchright + BROWSER_SLOTS
like the backend). Step 1 changed transport only: the Claude Code CLI with a
{url} JSON schema instead of the Anthropic SDK plus "first line starting with
http" parsing, so prompts/bike_photos.md says WebSearch instead of web_search
and asks for {"url": …} instead of a bare URL line. The CLI gets WebSearch
only — no WebFetch — so text injected into a search result cannot make it
fetch arbitrary URLs.

Deliberate differences from the backend: a CLI failure raises SearcherError
(502 — the UI button becomes clickable again) where the backend swallowed an
API error into photos: []; and because the page URL comes out of an LLM
reading the web while the browser runs inside our network, every request the
browser makes (the page, redirect hops, sub-resources, fetch/XHR, JS
navigations) goes through a route guard that aborts non-http(s) schemes and
hosts that are not public (is_public_http_url); scraped image URLs pointing at
a local name or a non-public IP literal are dropped (is_safe_image_url).
Accepted limitation: DNS rebinding — the host is resolved by the guard and
again by Chromium, and the two answers could differ.
"""
import asyncio
import ipaddress
import logging
import re
import socket
import time
from urllib.parse import urlsplit

from . import config
from .browser_config import BROWSER_SLOTS, playwright_headless
from .claude_cli import ClaudeCliError, run_structured
from .olx_finder import URL_MAX_LEN, searcher_error

logger = logging.getLogger("searcher.photos")

PROMPT_FILE = config.PROMPTS_DIR / "bike_photos.md"
MAX_PHOTOS = 8
CLI_TOOLS = "WebSearch"  # the product URL comes from search results; WebFetch is not needed

URL_SCHEMA = {
    "type": "object",
    "properties": {"url": {"type": "string"}},
    "required": ["url"],
}

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

_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
_LEGACY_IPV4 = re.compile(r"[0-9a-fx.]+", re.IGNORECASE)
# Belt and braces for Cloud Run: Chromium itself cannot resolve the metadata server's name.
_LAUNCH_ARGS = ["--host-resolver-rules=MAP metadata.google.internal ~NOTFOUND"]


def _ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address when `host` is an IP literal in any form a browser accepts
    (dotted, IPv6, and the legacy decimal / hex / octal IPv4 forms such as
    2130706433 or 0x7f.1), else None."""
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    if _LEGACY_IPV4.fullmatch(host) and any(c.isdigit() for c in host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _is_public_ip(addr) -> bool:
    return addr.is_global and not addr.is_multicast


def _split_http(url: str) -> tuple[str, int] | None:
    """(lower-cased host, port) of an http(s) URL without credentials and not
    on a local name, else None."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password:
        return None
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return None
    return host, port or (443 if parts.scheme == "https" else 80)


def _host_is_public(host: str, port: int) -> bool:
    """Every address `host` resolves to is public. Blocking (DNS)."""
    literal = _ip_literal(host)
    if literal is not None:
        return _is_public_ip(literal)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    try:
        addresses = {ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos}
    except ValueError:
        return False
    return bool(addresses) and all(_is_public_ip(a) for a in addresses)


def is_public_http_url(url: str) -> bool:
    """True when `url` is http(s) and its host resolves only to public addresses.

    Rejects other schemes, credentials in the URL, localhost / *.local /
    *.internal names (metadata.google.internal included), IP literals in any
    form that are not global, and any host whose addresses include a private,
    loopback, link-local, reserved or multicast one. Blocking (DNS) — call it
    from a worker thread.
    """
    split = _split_http(url)
    return split is not None and _host_is_public(*split)


def is_safe_image_url(url: str) -> bool:
    """String-only check for a stored image URL (no DNS): http(s), not a local
    name, not a non-global IP literal. Every viewer's browser loads it as <img>."""
    split = _split_http(url)
    if split is None:
        return False
    literal = _ip_literal(split[0])
    return literal is None or _is_public_ip(literal)


async def _find_product_url(prompt_file, user_message: str) -> str:
    """The manufacturer product page the model found, "" when none. Raises SearcherError when the CLI fails."""
    system_prompt = prompt_file.read_text(encoding="utf-8")
    try:
        # Blocking subprocess → worker thread, so /health keeps answering meanwhile.
        data = await asyncio.to_thread(run_structured, system_prompt, user_message, URL_SCHEMA, CLI_TOOLS)
    except ClaudeCliError as exc:
        raise searcher_error(exc) from exc
    url = str(data.get("url", "")).strip()
    if len(url) > URL_MAX_LEN:
        logger.warning("photos: product url longer than %d chars — ignored | url=%r", URL_MAX_LEN, url[:200])
        return ""
    return url if url.startswith("http") else ""


class _RouteGuard:
    """Playwright route handler: lets a request through only when its URL is
    http(s) on a public host. Host verdicts are cached for one scrape."""

    def __init__(self) -> None:
        self.verdicts: dict[tuple[str, int], bool] = {}
        self.aborted = 0
        self.allowed = 0

    def __call__(self, route) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:")):  # in-page content, never a network request
            route.continue_()
            return
        split = _split_http(url)
        ok = False
        if split is not None:
            if split not in self.verdicts:
                self.verdicts[split] = _host_is_public(*split)
            ok = self.verdicts[split]
        if ok:
            self.allowed += 1
            route.continue_()
        else:
            self.aborted += 1
            logger.warning("photos: browser request blocked (not a public http(s) address) | url=%r", url[:200])
            route.abort("blockedbyclient")


def _scrape_images_sync(url: str) -> list[str]:
    from patchright.sync_api import sync_playwright  # heavy import, deferred

    if not is_public_http_url(url):
        logger.warning("photos: product url rejected (not a public http(s) address) | url=%r", url[:200])
        return []

    t = time.perf_counter()
    guard = _RouteGuard()
    try:
        with BROWSER_SLOTS, sync_playwright() as p:   # slot first: the node driver counts too
            browser = p.chromium.launch(headless=playwright_headless(), args=_LAUNCH_ARGS)
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                    service_workers="block",  # a service worker's requests would bypass the route guard
                )
                context.route("**/*", guard)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                html = page.content()
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("playwright scrape failed | url=%r error=%s aborted=%d", url, exc, guard.aborted)
        return []

    seen: set[str] = set()
    result: list[str] = []
    for raw in _IMG_SRC.findall(html):
        src = raw.strip()
        if not src.startswith("http"):
            continue
        if _SKIP.search(src):
            continue
        if len(src) > URL_MAX_LEN or not is_safe_image_url(src):  # String(2048) column; local / private hosts
            continue
        if src not in seen:
            seen.add(src)
            result.append(src)
        if len(result) >= MAX_PHOTOS:
            break

    logger.info(
        "photos scraped | url=%r count=%d elapsed=%.2fs requests_allowed=%d requests_aborted=%d hosts=%d",
        url,
        len(result),
        time.perf_counter() - t,
        guard.allowed,
        guard.aborted,
        len(guard.verdicts),
    )
    return result


async def find_product_photos(prompt_file, user_message: str, label: str) -> tuple[list[str], str]:
    """(photo URLs in page order, product page URL) for any product: one WebSearch-only CLI run under
    `prompt_file` for the manufacturer page, then the guarded scrape. Shared by the bike and the
    equipment photo searches (TODO-042); `label` only names the item in the log. Raises SearcherError
    when the CLI run fails; no product page / a failed scrape is ([], url) — not an error."""
    t = time.perf_counter()
    product_url = await _find_product_url(prompt_file, user_message)
    logger.info("photos: product url | item=%s url=%r elapsed=%.2fs", label, product_url, time.perf_counter() - t)
    if not product_url:
        logger.info("photos: no product URL found for %s", label)
        return [], ""

    logger.info("photos: scraping %r", product_url)
    try:
        photos = await asyncio.to_thread(_scrape_images_sync, product_url)
    except Exception as exc:
        logger.error("photos scrape error (non-fatal) | %s", exc)
        return [], product_url

    return photos, product_url


async def find_bike_photos(company: str, model: str) -> tuple[list[str], str]:
    """(photo URLs in page order, product page URL) for a bike — see find_product_photos."""
    user_message = f"Find the official product page URL for the {company} {model} bicycle on the manufacturer's website."
    return await find_product_photos(PROMPT_FILE, user_message, f"{company!r} {model!r}")
