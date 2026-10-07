"""The parts catalogue's part types (TODO-046) — the "Wyszukiwanie części" tab.

`equipment.part_type` holds one of these slugs (NULL = unknown, e.g. a row made by
a click in a bike's spec tree). The English name goes to the equipment searcher as
the element type of a catalogue part (no bike context) and to the AI prompts; the
Polish labels live in the frontend (frontend/src/partTypes.ts) — keep the two lists
in step. Helmets, lights, locks, apparel, forks and shocks are deliberately absent.
"""
from typing import Literal, Optional, get_args

PartType = Literal[
    "cassette", "chain", "rear_derailleur", "shifter", "crankset", "bottom_bracket",
    "brake", "rotor", "tyre", "wheel", "cockpit", "seat",
]
PART_TYPES: tuple[str, ...] = get_args(PartType)

PART_TYPE_NAMES: dict[str, str] = {
    "cassette": "Cassette",
    "chain": "Chain",
    "rear_derailleur": "Rear derailleur",
    "shifter": "Shifter",
    "crankset": "Crankset",
    "bottom_bracket": "Bottom bracket",
    "brake": "Brake",
    "rotor": "Brake rotor",
    "tyre": "Tyre",
    "wheel": "Wheel",
    "cockpit": "Handlebar / stem",
    "seat": "Saddle / seatpost",
}


def valid_part_type(value) -> Optional[str]:
    """The slug when `value` is one of the 12 (case and surrounding whitespace ignored), else None."""
    if not isinstance(value, str):
        return None
    slug = value.strip().lower()
    return slug if slug in PART_TYPE_NAMES else None


def part_type_name(slug: Optional[str]) -> str:
    """English name of a slug ("Cassette"), "" for None / an unknown slug."""
    return PART_TYPE_NAMES.get(slug or "", "")
