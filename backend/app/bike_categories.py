"""Closed list of bike categories (the `bike.category` column; NULL = unknown).

English values, stored as is. Nothing validates on write — this is the one place
the list lives. Dependency-free on purpose: the migration script and the discovery
scraper import it. The search form's category filter maps onto it below.
"""
from typing import Optional

BIKE_CATEGORIES = [
    "MTB", "Gravel", "Road", "Cyclocross", "Trekking", "Cross", "City", "Kids",
    "Youth", "Balance", "Triathlon", "Folding", "BMX", "Electric", "Electric cargo",
    "Hybrid/Commuter", "Touring", "Cruiser",
]

# centrumrowerowe.pl bike_type (Polish, looked up by strip().lower()) -> category.
# Keys are already lower-case.
POLISH_TO_CATEGORY = {
    "mtb": "MTB",
    "gravel": "Gravel",
    "szosowy": "Road",
    "przełajowy": "Cyclocross",
    "trekkingowy": "Trekking",
    "crossowy": "Cross",
    "miejski": "City",
    "dziecięcy": "Kids",
    "młodzieżowy": "Youth",
    "biegowy": "Balance",
    "jeździk dziecięcy": "Balance",
    "triathlonowy": "Triathlon",
    "składak": "Folding",
    "bmx": "BMX",
    "elektryczny": "Electric",
    "elektryczny cargo": "Electric cargo",
}


def category_from_discovery(bike_type: Optional[str]) -> Optional[str]:
    """Category for a discovery `bike_type`; '' / None / unknown -> None."""
    if not bike_type:
        return None
    return POLISH_TO_CATEGORY.get(bike_type.strip().lower())


# ── Search by category (SearchRequest.bike_type) ────────────────────────────
# The search form's "Typ roweru" values (frontend SearchInput.tsx BIKE_TYPES) and
# the only values /v1/bike/parse may extract.
SEARCH_BIKE_TYPES = ("Road", "MTB", "Gravel", "Hybrid/Commuter", "Touring", "BMX", "Folding")

# A form value -> the bike.category values it matches. A value not listed here
# (Road, MTB, … or an old address's "Cruiser") matches exactly itself.
SEARCH_TYPE_CATEGORIES = {
    "Hybrid/Commuter": ("City", "Cross", "Hybrid/Commuter"),
    "Touring": ("Trekking", "Touring"),
}

# A form value -> the category stamped on an AI-found bike whose category is NULL.
SEARCH_TYPE_STAMP = {"Hybrid/Commuter": "City", "Touring": "Trekking"}

_CANONICAL = {c.lower(): c for c in BIKE_CATEGORIES}


def _canonical_type(bike_type: Optional[str]) -> Optional[str]:
    """The form value with its canonical casing ('mtb' -> 'MTB'); unknown -> stripped as given."""
    if not bike_type or not bike_type.strip():
        return None
    value = bike_type.strip()
    return _CANONICAL.get(value.lower(), value)


def categories_for_search(bike_type: Optional[str]) -> frozenset[str]:
    """Lower-cased bike.category values a search `bike_type` matches; empty when none is given."""
    value = _canonical_type(bike_type)
    if value is None:
        return frozenset()
    return frozenset(c.lower() for c in SEARCH_TYPE_CATEGORIES.get(value, (value,)))


def category_for_ai_result(bike_type: Optional[str]) -> Optional[str]:
    """Category to stamp on an AI-found bike for a search `bike_type`; None when not in BIKE_CATEGORIES."""
    value = _canonical_type(bike_type)
    if value is None:
        return None
    stamp = SEARCH_TYPE_STAMP.get(value, value)
    return stamp if stamp in BIKE_CATEGORIES else None


def search_type_from_parse(value: object) -> Optional[str]:
    """A parsed `bike_type` kept only when it is one of SEARCH_BIKE_TYPES (canonical casing)."""
    if not isinstance(value, str):
        return None
    wanted = value.strip().lower()
    return next((t for t in SEARCH_BIKE_TYPES if t.lower() == wanted), None)
