import os
import threading


def playwright_headless() -> bool:
    """PLAYWRIGHT_HEADLESS=true for servers/containers (no display); unset keeps the visible local browser."""
    return os.getenv("PLAYWRIGHT_HEADLESS", "false").strip().lower() in ("1", "true", "yes")


def browser_max_concurrency() -> int:
    """BROWSER_MAX_CONCURRENCY: simultaneous browser launches per process; default 2, never below 1."""
    raw = os.getenv("BROWSER_MAX_CONCURRENCY", "2").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


# Process-wide cap on simultaneous browser launches. One slot = one Playwright node driver plus one
# Chromium process tree, 0.5–0.9 GiB measured on real product pages. Every scraper launches its own
# browser from a worker thread and nothing else limits how many run at once, so a burst of uncached
# details/offer requests would blow through Cloud Run's 2 GiB and get the whole instance killed
# (cached requests on it included). Callers block here until a slot frees; the event loop keeps serving.
BROWSER_MAX_CONCURRENCY = browser_max_concurrency()
BROWSER_SLOTS = threading.BoundedSemaphore(BROWSER_MAX_CONCURRENCY)
