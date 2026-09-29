"""centrumrowerowe.pl product page → BikeDetailsResponse, without AI.

Pure: no network, no DB. `parse_product(html, url)` reads

- the JSON-LD `Product` block (name, brand, description, image, category),
- the "Specyfikacja" table (`.product-spec .prod-feature` sections of
  label/value rows, including the e-bike "Silnik" / "Akumulator" boxes),
- the variant selector (`.parameters-section .parameter`) for every
  manufacturer frame size and wheel size of the product, not only the variant
  the page happens to show,
- the marketing article (`.product-desc .fr-wrapper`) and the photo gallery.

Polish labels are mapped to the backend's English tree by `spec_mapping`.
Every string is fitted to its `app.models` column, because PostgreSQL rejects
what SQLite silently stores.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models import Bike, BikeDetailComponent, BikeDetailPhoto  # noqa: E402 — needs sys.path above
from app.schemas import (  # noqa: E402
    BikeCategory, BikeDescription, BikeDetailsResponse, BikeSubcategory,
    ComponentElement, SpecItem, TextSegment,
)

import spec_mapping as sm  # noqa: E402

MAX_PHOTOS = 8
MAX_SENTENCES = 5


def _column_len(model, column: str) -> Optional[int]:
    return getattr(model.__table__.c[column].type, "length", None)  # None for Text


# Column sizes the parsed output must fit (None = unbounded Text).
LIMITS = {
    "brand": _column_len(Bike, "brand"),
    "model": _column_len(Bike, "model"),
    "category": _column_len(BikeDetailComponent, "category"),
    "subcategory": _column_len(BikeDetailComponent, "subcategory"),
    "element_name": _column_len(BikeDetailComponent, "element_name"),
    "element_description": _column_len(BikeDetailComponent, "element_description"),
    "spec_key": _column_len(BikeDetailComponent, "spec_key"),
    "spec_value": _column_len(BikeDetailComponent, "spec_value"),
    "photo_url": _column_len(BikeDetailPhoto, "url"),
}

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9„\"])")
_PARENS = re.compile(r"\s*\([^)]*\)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")  # get_text(" ") around <strong>6061</strong>,
_ELECTRIC_WORD = "elektryczn"


class ParseError(Exception):
    """The page is not a parseable bike product page."""


def fit(text: str, limit: Optional[int]) -> str:
    """Cut `text` to `limit` chars at a word boundary, ending with '…'."""
    if limit is None or len(text) <= limit:
        return text
    cut = text[:limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-/") + "…"


@dataclass
class ParsedBike:
    brand: str
    model: str
    raw_name: str
    bike_type: Optional[str]
    description: str
    photos: list[str] = field(default_factory=list)
    components: list[BikeCategory] = field(default_factory=list)
    frame_sizes: list[str] = field(default_factory=list)
    is_electric: bool = False

    def to_details_response(self, company: str, model: str) -> BikeDetailsResponse:
        text = self.description
        return BikeDetailsResponse(
            company=fit(company, LIMITS["brand"]),
            model=fit(model, LIMITS["model"]),
            description=BikeDescription(
                text=text,
                segments=[TextSegment(text=text)] if text else [],
                citations=[],
            ),
            components=[c.model_copy(deep=True) for c in self.components],
            photos=list(self.photos),
        )


# ── JSON-LD ──────────────────────────────────────────────────────────────


def _clean(text: Optional[str]) -> str:
    return " ".join(html_lib.unescape(text or "").replace("\xa0", " ").split())


def _text(value: Any) -> str:
    """A JSON-LD field as text, whatever shape it came in (str, number, list, dict)."""
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "@value", "text", "url", "contentUrl"):
            if (found := _text(value.get(key))):
                return found
        return ""
    if isinstance(value, list):
        return next((t for t in (_text(v) for v in value) if t), "")
    return ""


def _texts(value: Any) -> list[str]:
    """Every text in a JSON-LD field that may be a list (e.g. `image`)."""
    items = value if isinstance(value, list) else [value]
    return [t for t in (_text(v) for v in items) if t]


def _is_product(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    kind = item.get("@type")
    return kind == "Product" or (isinstance(kind, list) and "Product" in kind)


def _ld_items(data: Any):
    """Flatten a top-level list and `@graph` wrappers."""
    if isinstance(data, list):
        for item in data:
            yield from _ld_items(item)
    elif isinstance(data, dict):
        yield data
        if isinstance(data.get("@graph"), list):
            yield from _ld_items(data["@graph"])


def _product_ld(soup: BeautifulSoup) -> Optional[dict]:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (TypeError, ValueError):
            continue  # a malformed block must not hide a later good one
        product = next((i for i in _ld_items(data) if _is_product(i)), None)
        if product is not None:
            return product
    return None


# ── identity ─────────────────────────────────────────────────────────────


def _is_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def _is_lower(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.islower() for c in letters)


def _display_brand(brand: str, soup: BeautifulSoup, texts: list[str]) -> str:
    """The shop writes brands in capitals (ROMET); find the real casing (Romet).

    1. the "Marka" info box title, 2. a mixed-case mention in the marketing
    text, 3. title-case when any word has ≥ 4 letters (LE GRAND → Le Grand,
    while KTM / BMC stay), 4. as given.
    """
    if not _is_upper(brand):
        return brand
    norm = brand.lower()
    for title in soup.select('section[data-category="Marka"] .title'):
        if _clean(title.get_text()).lower() == norm:
            return _clean(title.get_text())
    pattern = re.compile(rf"(?<!\w){re.escape(brand)}(?!\w)", re.I)
    for text in texts:
        for match in pattern.finditer(text):
            found = match.group(0)
            if not _is_upper(found) and not _is_lower(found):
                return found
    if any(sum(c.isalpha() for c in word) >= 4 for word in brand.split()):
        return " ".join(word.title() for word in brand.split())
    return brand


def _split_name(raw_name: str, brand: str) -> tuple[Optional[str], str, str]:
    """(bike_type, brand-as-written, model) — brand located in the name."""
    if brand:
        match = re.search(rf"(?<!\w){re.escape(brand)}(?!\w)", raw_name, re.I)
        if match:
            prefix = raw_name[:match.start()].strip()
            prefix = re.sub(r"^rower\b", "", prefix, flags=re.I).strip()
            return prefix or None, match.group(0), raw_name[match.end():].strip()
    try:
        from name_split import split_name  # owned by db-scraper; optional here
        parts = split_name(raw_name)
        return parts.bike_type, parts.company, parts.model
    except Exception:  # noqa: BLE001 — fall back to the local heuristic
        pass
    tokens = raw_name.split()
    if tokens and tokens[0].lower() == "rower":
        tokens = tokens[1:]
    types = []
    while tokens and _is_lower(tokens[0]):
        types.append(tokens.pop(0))
    company = []
    while tokens and _is_upper(tokens[0]):
        company.append(tokens.pop(0))
    return " ".join(types) or None, " ".join(company), " ".join(tokens)


# ── page sections ────────────────────────────────────────────────────────


def _spec_rows(soup: BeautifulSoup) -> list[tuple[str, str, str]]:
    """(section, label, value) for every row of the Specyfikacja table."""
    rows = []
    for feature in soup.select(".product-spec .prod-feature"):
        heading = feature.find(["button", "p"], class_="h3")
        section = sm.normalise_label(heading.get_text(" ", strip=True) if heading else "")
        for li in feature.select("li"):
            label, value = li.select_one(".label"), li.select_one(".value")
            if label is None or value is None:
                continue
            rows.append((section, _clean(label.get_text(" ")), _clean(value.get_text(" "))))
    return rows


def _selector_values(soup: BeautifulSoup) -> dict[str, list[str]]:
    """Variant selector: normalised label ('rozmiar producenta') → shown values."""
    out: dict[str, list[str]] = {}
    for param in soup.select(".parameters-section .parameter"):
        label = param.select_one(".label")
        if label is None:
            continue
        key = sm.normalise_label(label.get_text(" ")).rstrip(":").strip()
        for value in param.select("li span.value"):
            text = _clean(value.get_text(" "))
            if text and text not in out.setdefault(key, []):
                out[key].append(text)
    return out


def _unique(values) -> list[str]:
    seen, out = set(), []
    for v in values:
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _decimal_dot(value: str) -> str:
    """'27,5"' → '27.5"': the backend's matchers split sizes on commas."""
    return re.sub(r"(\d),(\d)", r"\1.\2", value)


def _size_token(value: str) -> str:
    """'M (164-178 cm)' → 'M', '19,5"' → '19.5"', '54 cm' → '54cm' (one token)."""
    value = _decimal_dot(_PARENS.sub("", value).strip())
    return re.sub(r"(\d)\s+(cm)\b", r"\1\2", value, flags=re.I)


def _frame_sizes(rows, selector: dict[str, list[str]]) -> list[str]:
    """Letter sizes of every variant, then every inch size known.

    The selector lists all variants; the table only the one on the page, so
    it is the fallback that keeps `Sizes` present whenever the page states a size.
    """
    table = {sm.FRAME_SIZE_LABEL: [], sm.FRAME_SIZE_INCH_LABEL: []}
    for _, label, value in rows:
        norm = sm.normalise_label(label)
        if norm in table and value.lower() not in sm.EMPTY_VALUES:
            table[norm].append(value)
    letters = selector.get(sm.FRAME_SIZE_LABEL, []) + table[sm.FRAME_SIZE_LABEL]
    inches = selector.get(sm.FRAME_SIZE_INCH_LABEL, []) + table[sm.FRAME_SIZE_INCH_LABEL]
    return _unique(_size_token(v) for v in letters + inches)


def _is_ebike(soup: BeautifulSoup, rows, raw_name: str, product: dict) -> bool:
    if soup.select(".electrical-features li"):
        return True
    if any(section in sm.ELECTRIC_SECTIONS for section, _, _ in rows):
        return True
    return _ELECTRIC_WORD in f"{raw_name} {_text(product.get('category'))}".lower()


def _description(soup: BeautifulSoup, product: dict) -> tuple[str, list[str]]:
    """First ~5 sentences of the marketing article (JSON-LD description as
    fallback — it is usually one SEO sentence), plus all texts for brand casing."""
    paragraphs = []
    for wrapper in soup.select(".product-desc .fr-wrapper"):
        for box in wrapper.select(".reusableBoxesGroup"):
            box.extract()
        paragraphs += [_clean(p.get_text(" ")) for p in wrapper.find_all("p")]
    article = _SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(p for p in paragraphs if p))
    ld_desc = _text(product.get("description"))
    source = article or ld_desc
    sentences = [s.strip() for s in _SENTENCE_END.split(source) if s.strip()]
    return " ".join(sentences[:MAX_SENTENCES]), [article, ld_desc]


def _usable_url(url: str) -> bool:
    parsed = urlparse(url)
    limit = LIMITS["photo_url"]
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and (limit is None or len(url) <= limit)


def _photos(soup: BeautifulSoup, product: dict, url: str) -> list[str]:
    """Gallery (largest size); JSON-LD / og:image only when there is none."""
    found = []
    for item in soup.select(".photo .list .item"):
        big = item.select_one("img.fullscreen-xl-m[data-default]")
        std = item.select_one("picture.standard img[src]")
        src = big["data-default"] if big else (std["src"] if std else None)
        if src and not src.endswith("blank.gif"):
            found.append(urljoin(url, src))
    if not found:
        found += [urljoin(url, i) for i in _texts(product.get("image"))]
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            found.append(urljoin(url, og["content"]))
    return _unique(u for u in found if _usable_url(u))[:MAX_PHOTOS]


# ── component tree ───────────────────────────────────────────────────────


class _Tree:
    """category → subcategory → [element dict], insertion-ordered."""

    def __init__(self) -> None:
        self.cats: dict[str, dict[str, list[dict]]] = {}

    def _elements(self, category: str, subcategory: str) -> list[dict]:
        return self.cats.setdefault(category, {}).setdefault(subcategory, [])

    def component(self, category: str, subcategory: str, name: str, description: str = "") -> None:
        name = fit(name, LIMITS["element_name"])
        elements = self._elements(category, subcategory)
        if not any(e["name"].lower() == name.lower() for e in elements):
            elements.append({"name": name, "description": description, "specs": []})

    def spec(self, category: str, subcategory: str, key: str, value: str, element: Optional[str] = None) -> None:
        elements = self._elements(category, subcategory)
        target = next((e for e in elements if element is None or e["name"] == element), None)
        if target is None:
            target = {"name": fit(element or subcategory, LIMITS["element_name"]), "description": "", "specs": []}
            elements.append(target)
        if not any(k.lower() == key.lower() for k, _ in target["specs"]):
            target["specs"].append((key, value))

    def build(self) -> list[BikeCategory]:
        order = {c: i for i, c in enumerate(sm.CATEGORY_ORDER)}
        return [
            BikeCategory(category=fit(cat, LIMITS["category"]), subcategories=[
                BikeSubcategory(subcategory=fit(sub, LIMITS["subcategory"]), elements=[
                    ComponentElement(
                        name=e["name"],
                        description=fit(e["description"], LIMITS["element_description"]),
                        specs=[SpecItem(key=fit(k, LIMITS["spec_key"]), value=fit(v, LIMITS["spec_value"]))
                               for k, v in e["specs"]],
                    ) for e in elements
                ]) for sub, elements in subs.items() if elements
            ])
            for cat, subs in sorted(self.cats.items(), key=lambda kv: order.get(kv[0], len(order)))
            if any(subs.values())
        ]


def _build_tree(rows, frame_sizes: list[str], wheel_sizes: list[str], is_ebike: bool) -> list[BikeCategory]:
    tree = _Tree()
    specs = []
    # Pass 1: components (so a spec with element=None attaches to the real part).
    for section, label, value in rows:
        norm = sm.normalise_label(label)
        if section in sm.SKIP_SECTIONS or norm in sm.SKIP_LABELS:
            continue
        if norm in (sm.FRAME_SIZE_LABEL, sm.WHEEL_SIZE_LABEL):
            continue  # filled below from every variant
        if value.lower() in sm.EMPTY_VALUES:
            continue
        mapping = sm.lookup(label)
        if mapping is not None and mapping.category == sm.ELECTRIC and not is_ebike:
            mapping = None  # 'Wyświetlacz' on a plain bike is a computer, not a powertrain
        if mapping is None:
            tree.component(sm.ACCESSORIES, sm.UNKNOWN_SUBCATEGORY, value, label)
        elif isinstance(mapping, sm.Spec):
            specs.append((mapping, value))
        else:
            tree.component(mapping.category, mapping.subcategory, value, mapping.description)
    # Pass 2: attributes.
    for mapping, value in specs:
        tree.spec(mapping.category, mapping.subcategory, mapping.key, value, mapping.element)
    if frame_sizes:
        tree.spec(sm.FRAME, "Frame", sm.SIZES_KEY, ", ".join(frame_sizes))
    if wheel_sizes:
        tree.spec(sm.WHEELS, "Wheelset", sm.WHEEL_SIZE_KEY, ", ".join(wheel_sizes))
    if is_ebike and sm.ELECTRIC not in tree.cats:
        tree.component(sm.ELECTRIC, "Motor", "Motor")
    return tree.build()


# ── entry point ──────────────────────────────────────────────────────────


def parse_product(html: str, url: str) -> ParsedBike:
    soup = BeautifulSoup(html or "", "html.parser")
    product = _product_ld(soup)
    if product is None:
        raise ParseError("no JSON-LD Product on the page")
    raw_name = _text(product.get("name"))
    if not raw_name:
        raise ParseError("JSON-LD Product has no name")
    rows = _spec_rows(soup)
    if not rows:
        raise ParseError("no Specyfikacja table on the page")

    spec_values = {sm.normalise_label(label): value for _, label, value in rows}
    ld_brand = _text(product.get("brand")) or spec_values.get("marka", "")
    bike_type, _, model = _split_name(raw_name, ld_brand)
    if not ld_brand:
        _, ld_brand, model = _split_name(raw_name, "")
    if not ld_brand or not model:
        raise ParseError(f"cannot split brand/model from {raw_name!r}")

    description, texts = _description(soup, product)
    brand = _display_brand(ld_brand, soup, texts + [raw_name])

    selector = _selector_values(soup)
    frame_sizes = _frame_sizes(rows, selector)
    wheel_sizes = _unique(_decimal_dot(v) for v in
                          [v for _, label, v in rows if sm.normalise_label(label) == sm.WHEEL_SIZE_LABEL]
                          + selector.get(sm.WHEEL_SIZE_LABEL, []))

    is_ebike = _is_ebike(soup, rows, raw_name, product)
    components = _build_tree(rows, frame_sizes, wheel_sizes, is_ebike)

    return ParsedBike(
        brand=fit(brand, LIMITS["brand"]),
        model=fit(model, LIMITS["model"]),
        raw_name=raw_name,
        bike_type=bike_type,
        description=description,
        photos=_photos(soup, product, url),
        components=components,
        frame_sizes=frame_sizes,
        is_electric=any(c.category == sm.ELECTRIC for c in components),
    )
