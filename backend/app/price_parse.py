"""Parse the free-text `price` strings stored on cached offers into floats.

`BikeOffer.price` is whatever the model scraped — `'2799 zł'`, `'17 386,85 zł'`,
`'1199.99 zł'`, or a non-numeric sentinel like `'Price on request'`. Polish
listings mix `,` and `.` decimals and use spaces (regular, NBSP or narrow NBSP)
as thousands separators, so the separator role has to be inferred per string.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Currency tokens seen in cached offers, longest first so 'zł' wins over 'zl'.
_CURRENCY = re.compile(r"(zł|pln|zl)", re.IGNORECASE)
# Regular space, NBSP and narrow NBSP all act as thousands separators.
_SPACES = re.compile(r"[\s  ]")
_KEEP = re.compile(r"[^0-9.,]")


def _strip_seps(text: str) -> str:
    return text.replace(",", "").replace(".", "")


def parse_price(raw: str) -> float | None:
    """Return the numeric value of a price string, or None if unknown.

    None means "no parseable price" — under TODO-009 decision 3 that is treated
    leniently (the bike passes a `price_max` filter). Never raises.
    """
    try:
        if not raw:
            return None
        s = _KEEP.sub("", _SPACES.sub("", _CURRENCY.sub("", raw)))
        if not any(c.isdigit() for c in s):
            return None

        comma, dot = s.rfind(","), s.rfind(".")
        last = max(comma, dot)
        if comma >= 0 and dot >= 0:
            # Both present: the last separator is the decimal point.
            decimal = True
        elif last >= 0:
            # A lone separator is a decimal point when at most 2 digits follow —
            # otherwise it groups thousands ('11.000', '1,234'). Prices are
            # scraped from several sites, so a 1-digit tail ('1,5') is far more
            # likely a real decimal than Polish grouping, which uses spaces.
            decimal = len(s) - last - 1 <= 2
        else:
            decimal = False

        if decimal:
            s = _strip_seps(s[:last]) + "." + _strip_seps(s[last + 1:])
        else:
            s = _strip_seps(s)
        return float(s)
    except Exception as exc:  # noqa: BLE001 — an unparseable price is just unknown
        logger.warning("parse_price failed (non-fatal) | raw=%r %s", raw, exc)
        return None
