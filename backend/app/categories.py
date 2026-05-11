from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"

BIKE_CATEGORIES: list[tuple[str, str]] = [
    ("Road", "road"),
    ("Mountain (MTB)", "mountain"),
    ("Gravel", "gravel"),
    ("Hybrid / Commuter", "hybrid"),
    ("Electric (e-bike)", "electric"),
    ("BMX", "bmx"),
    ("Cruiser", "cruiser"),
    ("Touring", "touring"),
    ("Folding", "folding"),
    ("Cyclocross", "cyclocross"),
    ("Kids", "kids"),
]

# Loaded at import time — fails fast on missing prompt file
CATEGORY_PROMPTS: dict[str, str] = {
    name: (PROMPTS_DIR / f"{slug}.md").read_text(encoding="utf-8")
    for name, slug in BIKE_CATEGORIES
}
