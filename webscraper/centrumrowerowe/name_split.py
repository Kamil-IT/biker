"""Heuristic split of a centrumrowerowe.pl listing name (TODO-035).

"Rower trekkingowy damski KROSS Trans 1.0" -> bike_type "trekkingowy", company "KROSS", model "Trans 1.0".
The worker later corrects company/model from the product page (JSON-LD brand), so this only
has to be good enough for the queue row. It never raises and never returns an empty company/model.
"""
import html
import re
from typing import NamedTuple, Optional

# Upper-case words that are bike types, not brands ("Rower MTB KROSS ...").
UPPER_TYPES = {"MTB", "BMX", "XC", "E-BIKE", "EBIKE", "CX"}
# Words in the type prefix that describe the rider, not the bike type.
RIDER_WORDS = {"damski", "męski", "meski", "unisex", "chłopięcy", "dziewczęcy", "juniorski"}
# Brands written as several upper-case words.
MULTI_WORD_BRANDS = ("VAN RYSEL", "ROSE BIKES", "BE ONE", "R RAYMON", "ELEKTRO BIKE")


class NameParts(NamedTuple):
    bike_type: Optional[str]
    company: str
    model: str


def _is_upper_word(token: str) -> bool:
    letters = [c for c in token if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def _is_type_word(token: str) -> bool:
    return (token.islower() and token.isalpha()) or token.upper() in UPPER_TYPES and token.isupper()


def _brand_len(tokens: list[str]) -> int:
    """Number of leading tokens that form the brand (multi-word brands first)."""
    for brand in MULTI_WORD_BRANDS:
        n = len(brand.split())
        if [t.upper() for t in tokens[:n]] == brand.split():
            return n
    return 1


def split_name(raw_name: str) -> NameParts:
    text = re.sub(r"\s+", " ", html.unescape(raw_name or "")).strip()
    tokens = text.split(" ") if text else []
    try:
        has_prefix = bool(tokens) and tokens[0].lower() == "rower"
        rest = tokens[1:] if has_prefix else tokens
        types: list[str] = []

        if has_prefix:
            while len(rest) > 1 and _is_type_word(rest[0]):
                types.append(rest.pop(0))
        else:
            # Without "Rower": everything before the first upper-case brand word is type text.
            idx = next((i for i, t in enumerate(rest)
                        if _is_upper_word(t) and t.upper() not in UPPER_TYPES), None)
            if idx:
                types, rest = rest[:idx], rest[idx:]

        if not rest:
            rest = types[-1:] or tokens or [text or "unknown"]
            types = types[:-1]
        n = _brand_len(rest)
        company = " ".join(rest[:n])
        model = " ".join(rest[n:]) or company
        kept = [t for t in types if t.lower() not in RIDER_WORDS]
        bike_type = " ".join(kept).strip() or None
        return NameParts(bike_type, company or "unknown", model or "unknown")
    except Exception:  # defensive: the queue must never lose a row over a name
        first = tokens[0] if tokens else "unknown"
        return NameParts(None, first, " ".join(tokens[1:]) or first)
