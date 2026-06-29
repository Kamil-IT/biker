from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"

# (display name, slug) — each slug has a matching app/prompts/equipment_details_{slug}.md
EQUIPMENT_CATEGORIES: list[tuple[str, str]] = [
    ("Helmets",                        "helmets"),
    ("Lights & electronics",           "lights"),
    ("Locks & security",               "locks"),
    ("Apparel, bags & accessories",    "apparel"),
]

# Loaded at import time — fails fast on a missing prompt file
EQUIPMENT_PROMPTS: dict[str, str] = {
    slug: (PROMPTS_DIR / f"equipment_details_{slug}.md").read_text(encoding="utf-8")
    for _, slug in EQUIPMENT_CATEGORIES
}

_DISPLAY_BY_SLUG: dict[str, str] = {slug: name for name, slug in EQUIPMENT_CATEGORIES}

# Keyword → slug inference. Checked in order; first hit wins. "apparel" is the catch-all.
_INFERENCE: list[tuple[str, list[str]]] = [
    ("helmets", ["helmet", "mips", "kask", "casque"]),
    ("lights",  ["light", "lamp", "lumen", "headlight", "taillight", "tail light",
                 "front light", "rear light", "computer", "gps", "garmin", "wahoo",
                 "electronic", "battery", "led", "reflector"]),
    ("locks",   ["lock", "u-lock", "ulock", "padlock", "chain lock", "kryptonite",
                 "abus", "security", "shackle"]),
    ("apparel", ["jersey", "glove", "shoe", "shorts", "bib", "jacket", "pannier",
                 "rack", "pump", "tool", "bottle", "cage", "bag", "saddlebag",
                 "fender", "mudguard", "apparel", "clothing"]),
]


def valid_slug(value: str | None) -> str | None:
    """Return the canonical slug if `value` matches a known category (by slug or name)."""
    if not value:
        return None
    v = value.strip().lower()
    if v in _DISPLAY_BY_SLUG:
        return v
    for name, slug in EQUIPMENT_CATEGORIES:
        if v == name.lower():
            return slug
    return None


def infer_category(company: str, model: str) -> str:
    """Infer an equipment category slug from the free-text item name. Defaults to 'apparel'."""
    text = f"{company} {model}".lower()
    for slug, keywords in _INFERENCE:
        if any(kw in text for kw in keywords):
            return slug
    return "apparel"


def resolve_category(company: str, model: str, category: str | None) -> str:
    """Use the caller's category when valid, otherwise infer it from the item name."""
    return valid_slug(category) or infer_category(company, model)


def display_name(slug: str) -> str:
    return _DISPLAY_BY_SLUG.get(slug, slug)
