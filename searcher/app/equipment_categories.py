"""Equipment category registry (TODO-042) — started as a copy of backend/app/equipment_categories.py.

The backend's 4 categories plus `parts` (bike components: drivetrain, brakes,
wheels, cockpit, saddle, pedals, suspension). Most elements clicked in a bike's
spec tree are parts, so `parts` is the default when no keyword matches;
`apparel` is chosen only on a keyword hit. The prompts are the searcher's CLI
versions in searcher/app/prompts/.

Keywords match at a word start (`(?<![a-z0-9])kw`), so "stem" does not hit
"system" and "led" does not hit "handled"; plurals still match ("tyres").
Several matches: the head noun (the latest keyword in the name) wins — see
infer_category.
"""
import re

from . import config

PROMPTS_DIR = config.PROMPTS_DIR

# (display name, slug) — each slug has a matching app/prompts/equipment_details_{slug}.md
EQUIPMENT_CATEGORIES: list[tuple[str, str]] = [
    ("Helmets",                        "helmets"),
    ("Lights & electronics",           "lights"),
    ("Locks & security",               "locks"),
    ("Apparel, bags & accessories",    "apparel"),
    ("Bike parts & components",        "parts"),
]
DEFAULT_SLUG = "parts"

# Loaded at import time — fails fast on a missing prompt file
EQUIPMENT_PROMPTS: dict[str, str] = {
    slug: (PROMPTS_DIR / f"equipment_details_{slug}.md").read_text(encoding="utf-8")
    for _, slug in EQUIPMENT_CATEGORIES
}

_DISPLAY_BY_SLUG: dict[str, str] = {slug: name for name, slug in EQUIPMENT_CATEGORIES}

_PARTS_KEYWORDS = [
    "derailleur", "shifter", "shift lever", "cassette", "freewheel", "crank", "chainring", "chain", "bottom bracket",
    "brake", "rotor", "caliper", "lever", "pad", "rim", "hub", "wheel", "tyre", "tire", "tube", "spoke", "axle",
    "handlebar", "stem", "grip", "bar tape", "tape", "headset", "seatpost", "seat post", "dropper", "saddle", "pedal",
    "fork", "shock", "suspension", "groupset", "sprocket", "motor", "drive unit",
    "lock-on", "lockring", "lock ring",              # part names that contain a lock keyword
    "battery", "battery pack", "powertube",          # an e-bike battery is a part (a light's battery: see below)
]

# Keyword lists per slug, in tie-break order (an earlier category wins an exact tie). Brand names are keywords
# too; as they usually come first in a name, any later keyword (the head noun) beats them.
_INFERENCE: list[tuple[str, list[str]]] = [
    ("helmets", ["helmet", "mips", "kask", "casque"]),
    ("locks",   ["lock", "u-lock", "ulock", "padlock", "chain lock", "frame lock", "battery lock", "cable lock",
                 "folding lock", "kryptonite", "abus", "security", "shackle"]),
    ("lights",  ["light", "lamp", "lumen", "headlight", "taillight", "tail light", "front light", "rear light",
                 "computer", "gps", "garmin", "wahoo", "electronic", "led", "reflector",
                 "lezyne", "cateye", "knog", "lupine", "sigma"]),
    ("apparel", ["jersey", "jacket", "bib", "shorts", "glove", "shoe", "sock", "vest", "gilet",
                 "bag", "saddlebag", "backpack", "pannier", "rack", "basket", "bottle", "cage", "pump", "tool",
                 "fender", "mudguard", "kickstand", "bell", "mirror", "apparel", "clothing"]),
    ("parts",   _PARTS_KEYWORDS),
]
_PATTERNS: list[tuple[int, str, str, re.Pattern]] = [
    (order, slug, kw, re.compile(r"(?<![a-z0-9])" + re.escape(kw)))
    for order, (slug, keywords) in enumerate(_INFERENCE) for kw in keywords
]
_LIGHT_WORDS = ("light", "lamp", "lumen", "led", "headlight", "taillight")


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
    """Infer a category slug from the free-text item name; no keyword → 'parts' (bike components).

    Head-noun rule: when several keywords match, the one that STARTS LATEST in
    the name wins (the head noun ends an English product name: "Abus T82
    Battery Lock" → lock, "Brake light" → light, "ODI Lock-On grips" → grip);
    at the same start the longer keyword wins ("lockring" over "lock",
    "saddlebag" over "saddle", "chain lock" over "chain"), then the earlier
    category. A battery wins as a part unless a light word is in the name too.
    """
    text = f"{company} {model}".lower()
    best = None  # (start, length, -order, slug, kw)
    for order, slug, kw, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            cand = (m.start(), len(kw), -order, slug, kw)
            if best is None or cand[:3] > best[:3]:
                best = cand
    if best is None:
        return DEFAULT_SLUG
    if best[4] in ("battery", "battery pack") and any(
        re.search(r"(?<![a-z0-9])" + w, text) for w in _LIGHT_WORDS
    ):
        return "lights"
    return best[3]


def resolve_category(company: str, model: str, category: str | None) -> str:
    """Use the caller's category when valid, otherwise infer it from the item name."""
    return valid_slug(category) or infer_category(company, model)


def display_name(slug: str) -> str:
    return _DISPLAY_BY_SLUG.get(slug, slug)
