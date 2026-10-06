"""Equipment category inference — a copy of searcher/app/equipment_categories.py (without the prompts).

POST /v1/equipment/resolve creates the equipment row of a clicked element BEFORE
any search runs, so it must pick the same category slug the searcher would
(the searcher's identity is (category, name_norm)): the keyword lists and
infer_category() below are verbatim copies. Change the searcher's first, then
this copy.
"""
import re

DEFAULT_SLUG = "parts"

_PARTS_KEYWORDS = [
    "derailleur", "shifter", "shift lever", "cassette", "freewheel", "crank", "chainring", "chain", "bottom bracket",
    "brake", "rotor", "caliper", "lever", "pad", "rim", "hub", "wheel", "tyre", "tire", "tube", "spoke", "axle",
    "handlebar", "stem", "grip", "bar tape", "tape", "headset", "seatpost", "seat post", "dropper", "saddle", "pedal",
    "fork", "shock", "suspension", "groupset", "sprocket", "motor", "drive unit", "frame", "frameset",
    "lock-on", "lockring", "lock ring",              # part names that contain a lock keyword
    "battery", "battery pack", "powertube",          # an e-bike battery is a part (a light's battery: see below)
]

# Keyword lists per slug, in tie-break order (an earlier category wins an exact tie).
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


def infer_category(company: str, model: str) -> str:
    """Category slug from the free-text item name; no keyword → 'parts'. The latest-starting keyword wins
    (the head noun), then the longer one, then the earlier category; a battery is a part unless a light word
    is in the name too."""
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
