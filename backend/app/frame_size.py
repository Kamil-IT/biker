"""Frame-size recommendation (TODO-045): a pure calculation from height, inseam and bike type.

No I/O, no database, no AI, no cache. The formulas, the letter table and the
measurement check live here; the frontend only sends the numbers and shows the answer.
"""
from bisect import bisect_right
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from .schemas import FitBikeType, FrameLetter, FrameSizeResponse


@dataclass(frozen=True)
class Formula:
    multiplier: Decimal  # frame size = inseam * multiplier + offset
    offset: Decimal
    unit: Literal["cm", "in"]
    half_range: Decimal  # the recommended range is size -/+ this, in `unit`
    confidence: Literal["good", "medium"]


# Decimal, not float: a result like 62.5 * 0.66 = 41.25 must round to 41.3, and in binary floats it lands just below.
FORMULAS: dict[str, Formula] = {
    "Road": Formula(Decimal("0.66"), Decimal("0"), "cm", Decimal("2"), "good"),
    "MTB": Formula(Decimal("0.226"), Decimal("0"), "in", Decimal("0.8"), "good"),
    "Gravel": Formula(Decimal("0.65"), Decimal("-1"), "cm", Decimal("2"), "medium"),
    "Touring": Formula(Decimal("0.66"), Decimal("0"), "cm", Decimal("2"), "medium"),
    "Hybrid/Commuter": Formula(Decimal("0.66"), Decimal("0"), "cm", Decimal("2"), "medium"),
}

LETTERS: tuple[FrameLetter, ...] = ("XS", "S", "M", "L", "XL")
# Lower bound of S, M, L, XL (XS is everything below the first): a size equal to a bound is in the upper letter.
LETTER_BOUNDS = {
    "cm": (50.0, 53.0, 56.0, 59.0),
    "in": (15.0, 17.0, 19.0, 21.0),
}

# inseam / height outside this (inclusive) closed range = the inseam was probably measured wrong.
INSEAM_RATIO_MIN, INSEAM_RATIO_MAX = 0.40, 0.50
RATIO_DECIMALS = 9  # 68.6 / 171.5 is exactly 0.4 on paper but 0.39999999999999997 as a float


def letter_index(size: float, unit: str) -> int:
    """Index into LETTERS for a size in `unit` (cm or in)."""
    return bisect_right(LETTER_BOUNDS[unit], size)


def letter_for(size: float, unit: str) -> FrameLetter:
    return LETTERS[letter_index(size, unit)]


def round_1(value: Decimal) -> float:
    """One decimal, halves up (41.25 -> 41.3) — what the rider sees in the answer."""
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def compute_frame_size(height_cm: float, inseam_cm: float, bike_type: FitBikeType) -> FrameSizeResponse:
    """The recommended frame size for the rider. Inputs are assumed already validated (see FrameSizeRequest).

    The arithmetic is decimal and the numbers are rounded to 1 decimal first (halves up); the letters
    come from those rounded values, so the answer never contradicts itself (a size shown as 53.0 is never an S).
    """
    f = FORMULAS[bike_type]
    raw = Decimal(str(inseam_cm)) * f.multiplier + f.offset  # str(): the digits the rider typed, not the binary float
    size, low, high = round_1(raw), round_1(raw - f.half_range), round_1(raw + f.half_range)
    ratio = round(inseam_cm / height_cm, RATIO_DECIMALS)
    return FrameSizeResponse(
        bike_type=bike_type,
        size=size,
        unit=f.unit,
        range_min=low,
        range_max=high,
        letter=letter_for(size, f.unit),
        letters=list(LETTERS[letter_index(low, f.unit):letter_index(high, f.unit) + 1]),
        confidence=f.confidence,
        measurement_warning=not INSEAM_RATIO_MIN <= ratio <= INSEAM_RATIO_MAX,
    )
