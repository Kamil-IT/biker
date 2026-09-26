"""Decathlon house-brand allowlist for POST /v1/bike/decathlon/search (TODO-032).

Decathlon sells (almost) only its own brands, so a search for a Trek or a
Canyon on decathlon.pl can never find anything — yet before TODO-032 every
such details view paid for a web search that came back empty, which is what
TODO_ISSUE_010 ("Decathlon offers always empty for non-Decathlon brands")
reported. The route now asks `is_decathlon_brand()` first and, for a foreign
brand, answers straight away with an empty list plus `not_sold_info()` as the
`info` text — no searcher run, no subscription search spent.

Brand names arrive in whatever casing and punctuation the search results used
("B'Twin", "Btwin", "B-TWIN", "Van Rysel", "VANRYSEL"), so the compare runs on a
normalised token: lower-case with apostrophes, hyphens, dots and whitespace
removed. To add a brand, append its normalised token to DECATHLON_BRANDS and its
display name to DECATHLON_BRAND_LABELS (the order there is the order shown to
the user). Verified against decathlon.pl on 2026-09-26.
"""

DECATHLON_BRANDS: frozenset[str] = frozenset({
    "rockrider",   # MTB
    "btwin",       # kids / folding — B'Twin, Btwin, B-Twin
    "triban",      # recreational road
    "vanrysel",    # road / gravel — Van Rysel
    "elops",       # city
    "riverside",   # hybrid
    "stilus",      # e-bikes
    "tilt",        # folding
    "decathlon",   # the store itself, as some listings name it
})

# Display names for the `info` sentence, in the order they are listed to the user.
DECATHLON_BRAND_LABELS: tuple[str, ...] = (
    "Rockrider", "Btwin", "Triban", "Van Rysel", "Elops", "Riverside", "Stilus", "Tilt",
)

_STRIPPED_CHARS = str.maketrans("", "", "'’-.")


def _normalise(company: str) -> str:
    """Lower-case token with apostrophes (' and ’), hyphens, dots and whitespace removed."""
    return "".join((company or "").lower().translate(_STRIPPED_CHARS).split())


def is_decathlon_brand(company: str) -> bool:
    """Whether `company` is one of Decathlon's house brands (normalised compare)."""
    return _normalise(company) in DECATHLON_BRANDS


def not_sold_info(company: str) -> str:
    """The Polish `info` sentence returned instead of a search for a foreign brand."""
    brands = ", ".join(DECATHLON_BRAND_LABELS)
    return (
        f"Decathlon nie sprzedaje marki {(company or '').strip()} — "
        f"w sklepie są tylko marki własne ({brands})."
    )
