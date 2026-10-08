"""Closed list of bike categories (the `bike.category` column; NULL = unknown).

TODO-047: eight codes, exactly the search form's "Typ roweru" values, enforced by the
database (`ck_bike_category`, see `category_check_sql`). This is the one place the list
lives. Dependency-free on purpose: models, the migration scripts and the discovery
scraper import it. Electric is not a type: an e-bike gets its type and is recognised as
electric by its `Electric / Powertrain` components.
"""
from typing import Optional

# Declaration order = display order of the search form.
BIKE_CATEGORIES = (
    "Road", "MTB", "Gravel", "City/Cross/Hybrid", "Touring", "BMX", "Folding", "Kids",
)

# Every value the column held before TODO-047 -> the code it became. "Electric" and
# "Electric cargo" are not here: they carry no type, so
# webscraper/centrumrowerowe/reclassify_ebikes.py reads it from the shop's product page.
LEGACY_CATEGORIES = {
    "Triathlon": "Road",
    "Dirt/Street": "MTB",
    "Cyclocross": "Gravel",
    "City": "City/Cross/Hybrid",
    "Cross": "City/Cross/Hybrid",
    "Hybrid/Commuter": "City/Cross/Hybrid",
    "Cruiser": "City/Cross/Hybrid",
    "Trekking": "Touring",
    "Youth": "Kids",
    "Balance": "Kids",
}
ELECTRIC_LEGACY = ("Electric", "Electric cargo")

# centrumrowerowe.pl bike_type (the Polish word of the product name, looked up by
# strip().lower()) -> category. Keys are already lower-case. "elektryczny" is missing
# on purpose: the name of an e-bike names no type, category_from_shop_path finds it.
POLISH_TO_CATEGORY = {
    "mtb": "MTB",
    "gravel": "Gravel",
    "szosowy": "Road",
    "przełajowy": "Gravel",
    "trekkingowy": "Touring",
    "crossowy": "City/Cross/Hybrid",
    "miejski": "City/Cross/Hybrid",
    "dziecięcy": "Kids",
    "młodzieżowy": "Kids",
    "biegowy": "Kids",
    "jeździk dziecięcy": "Kids",
    "triathlonowy": "Road",
    "składak": "Folding",
    "bmx": "BMX",
    "elektryczny cargo": "City/Cross/Hybrid",
}

# The shop's product category path (JSON-LD Product.category, e.g.
# "Rowery > Elektryczne > Szosowe i gravelowe") -> category. Each segment is tried from
# the last one up; the first rule whose word occurs in it wins, so "gravel" comes before
# "szosow" and "Szosowe i gravelowe" is Gravel. "Elektryczne" alone matches nothing.
_SHOP_PATH_RULES = (
    ("gravel", "Gravel"), ("przełaj", "Gravel"),
    ("szosow", "Road"), ("triathlon", "Road"), ("czasow", "Road"),
    ("górsk", "MTB"), ("mtb", "MTB"), ("dirt", "MTB"),
    ("trekking", "Touring"), ("suv", "Touring"),
    ("miejsk", "City/Cross/Hybrid"), ("crossow", "City/Cross/Hybrid"), ("cargo", "City/Cross/Hybrid"),
    ("dziecię", "Kids"), ("młodzież", "Kids"), ("biegow", "Kids"), ("jeździk", "Kids"),
    ("składa", "Folding"), ("bmx", "BMX"),
)


def category_from_shop_path(path: Optional[str]) -> Optional[str]:
    """Category for a shop category path ('Rowery > Elektryczne > Trekkingowe' -> Touring); unknown -> None."""
    if not path:
        return None
    for segment in reversed([s.strip().lower() for s in path.split(">")]):
        for word, category in _SHOP_PATH_RULES:
            if word in segment:
                return category
    return None


def category_from_discovery(bike_type: Optional[str], shop_path: Optional[str] = None) -> Optional[str]:
    """Category for a discovery `bike_type`, else for the shop category path; '' / None / unknown -> None."""
    if bike_type and (found := POLISH_TO_CATEGORY.get(bike_type.strip().lower())):
        return found
    return category_from_shop_path(shop_path)


def category_check_sql(column: str = "category") -> str:
    """The `ck_bike_category` condition: NULL or one of BIKE_CATEGORIES."""
    values = ", ".join(f"'{c}'" for c in BIKE_CATEGORIES)
    return f"{column} IS NULL OR {column} IN ({values})"


# ── Search by category (SearchRequest.bike_type) ────────────────────────────
# The search form's "Typ roweru" values (frontend SearchInput.tsx BIKE_TYPES) and the
# only values /v1/bike/parse may extract: the categories themselves.
SEARCH_BIKE_TYPES = BIKE_CATEGORIES

_CANONICAL = {c.lower(): c for c in BIKE_CATEGORIES}
_LEGACY = {old.lower(): new for old, new in LEGACY_CATEGORIES.items()}


def canonical_category(value: object) -> Optional[str]:
    """A category code in its canonical casing; an old value (an old address) -> its new code; else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    key = value.strip().lower()
    return _CANONICAL.get(key) or _LEGACY.get(key)


def categories_for_search(bike_type: Optional[str]) -> frozenset[str]:
    """Lower-cased bike.category values a search `bike_type` matches; empty when none is given.

    A code also matches its old values, so a database not yet through
    migrate_bike_category_codes.py answers the same. An unknown value matches only
    itself (nothing), so the search falls back to the AI instead of listing every bike.
    """
    if not bike_type or not bike_type.strip():
        return frozenset()
    code = canonical_category(bike_type)
    if code is None:
        return frozenset({bike_type.strip().lower()})
    return frozenset({code.lower()} | {old.lower() for old, new in LEGACY_CATEGORIES.items() if new == code})


def category_for_ai_result(bike_type: Optional[str]) -> Optional[str]:
    """Category to stamp on an AI-found bike for a search `bike_type`; None when it is no category."""
    return canonical_category(bike_type)


def search_type_from_parse(value: object) -> Optional[str]:
    """A parsed `bike_type` kept only when it names a category (canonical code)."""
    return canonical_category(value)
