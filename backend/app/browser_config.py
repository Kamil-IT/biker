import os


def playwright_headless() -> bool:
    """PLAYWRIGHT_HEADLESS=true for servers/containers (no display); unset keeps the visible local browser."""
    return os.getenv("PLAYWRIGHT_HEADLESS", "false").strip().lower() in ("1", "true", "yes")
