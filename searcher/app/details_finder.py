"""Bike details search (TODO-041) — description, short description and the component tree in ONE CLI run.

Replaces the backend's 8 per-category `web_search` calls plus the description
call with a single `claude -p` turn (WebSearch + WebFetch, no Playwright,
subscription-billed) under prompts/bike_details.md. The CLI returns
`structured_output`, a dict validated against DETAILS_SCHEMA, so nothing is
dug out of prose. build_details() turns it into the backend's
BikeDetailsResponse shape; it is pure (no I/O) so it is unit-testable.

The CLI has no per-block citations, so BikeDescription is built from the
model's `sources`: text = description, one segment carrying every source,
`citations` = the sources with cited_text "".
"""
import asyncio
import logging
import time
from urllib.parse import urlsplit

from . import config
from .claude_cli import ClaudeCliError, run_structured
from .olx_finder import URL_MAX_LEN, searcher_error
from .schemas import (
    BikeCategory,
    BikeDescription,
    BikeDetails,
    BikeSubcategory,
    ComponentElement,
    DescriptionCitation,
    SpecItem,
    TextSegment,
)

logger = logging.getLogger("searcher.details")

PROMPT_FILE = config.PROMPTS_DIR / "bike_details.md"

# The 8 category shells the tree always carries, in display order.
CATEGORIES = (
    "Frame", "Drivetrain", "Brakes", "Wheels", "Cockpit", "Saddle & Seatpost", "Lighting", "Accessories",
)
# Column widths of bike_component (PostgreSQL rejects what SQLite stores).
CATEGORY_MAX, SUBCATEGORY_MAX, ELEMENT_NAME_MAX, SPEC_KEY_MAX, SPEC_VALUE_MAX = 255, 255, 512, 255, 1024
DESCRIPTION_MAX, SHORT_DESCRIPTION_MAX, ELEMENT_DESCRIPTION_MAX = 4000, 1000, 1000
TITLE_MAX, MAX_SOURCES = 255, 8

_STR = {"type": "string"}
DETAILS_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "description": _STR,
        "short_description": _STR,
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"url": _STR, "title": _STR},
                "required": ["url", "title"],
            },
        },
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": _STR,
                    "subcategories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "subcategory": _STR,
                                "elements": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": _STR,
                                            "description": _STR,
                                            "is_linkable": {"type": "boolean"},
                                            "specs": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {"key": _STR, "value": _STR},
                                                    "required": ["key", "value"],
                                                },
                                            },
                                        },
                                        "required": ["name", "description", "is_linkable", "specs"],
                                    },
                                },
                            },
                            "required": ["subcategory", "elements"],
                        },
                    },
                },
                "required": ["category", "subcategories"],
            },
        },
    },
    "required": ["found", "description", "short_description", "sources", "components"],
}


def _text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _is_http_url(url: str) -> bool:
    if not url or len(url) > URL_MAX_LEN:
        return False
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _sources(raw) -> list[DescriptionCitation]:
    """http(s) sources only (they are rendered as links), de-duplicated, capped."""
    out: list[DescriptionCitation] = []
    seen: set[str] = set()
    for entry in _list(raw):
        if not isinstance(entry, dict):
            continue
        url = _text(entry.get("url"), URL_MAX_LEN)
        if not _is_http_url(url) or url in seen:
            continue
        seen.add(url)
        out.append(DescriptionCitation(url=url, title=_text(entry.get("title"), TITLE_MAX) or url, cited_text=""))
        if len(out) >= MAX_SOURCES:
            break
    return out


def _components(raw) -> list[BikeCategory]:
    """The model's tree -> the 8 category shells in fixed order (see parse_categories)."""
    return parse_categories(raw, CATEGORIES)


def parse_categories(raw, shells: tuple[str, ...] = ()) -> list[BikeCategory]:
    """The model's tree -> categories, `shells` first in their order, strings capped to the column widths.

    A category the model repeats is merged; one it invents (not among the
    shells) is appended after them; an element without a name is dropped
    (nothing to store); a spec without a key is dropped. Shared with the
    equipment details search (no shells there).
    """
    by_name: dict[str, BikeCategory] = {name: BikeCategory(category=name) for name in shells}
    for cat in _list(raw):
        if not isinstance(cat, dict):
            continue
        name = _text(cat.get("category"), CATEGORY_MAX)
        if not name:
            continue
        target = by_name.setdefault(name, BikeCategory(category=name))
        for sub in _list(cat.get("subcategories")):
            if not isinstance(sub, dict):
                continue
            sub_name = _text(sub.get("subcategory"), SUBCATEGORY_MAX)
            if not sub_name:
                continue
            elements: list[ComponentElement] = []
            for el in _list(sub.get("elements")):
                if not isinstance(el, dict):
                    continue
                el_name = _text(el.get("name"), ELEMENT_NAME_MAX)
                if not el_name:
                    continue
                specs = [
                    SpecItem(key=_text(sp.get("key"), SPEC_KEY_MAX), value=_text(sp.get("value"), SPEC_VALUE_MAX))
                    for sp in _list(el.get("specs"))
                    if isinstance(sp, dict) and _text(sp.get("key"), SPEC_KEY_MAX)
                ]
                elements.append(ComponentElement(
                    name=el_name, description=_text(el.get("description"), ELEMENT_DESCRIPTION_MAX), specs=specs,
                    # ISSUE-016: only a literal true counts; a missing or malformed flag is "not a product".
                    is_linkable=el.get("is_linkable") is True,
                ))
            if elements:
                target.subcategories.append(BikeSubcategory(subcategory=sub_name, elements=elements))
    return list(by_name.values())


def has_components(details: BikeDetails) -> bool:
    return any(sub.elements for cat in details.components for sub in cat.subcategories)


def is_usable_details(details: BikeDetails) -> bool:
    """Worth storing: a non-empty component tree OR a non-empty description (never an all-empty run)."""
    return has_components(details) or bool(details.description.text.strip())


def empty_details(company: str, model: str) -> BikeDetails:
    return BikeDetails(company=company, model=model)


def build_description(raw_text, sources: list[DescriptionCitation]) -> BikeDescription:
    """Description text (capped) + one segment carrying every source; empty text -> empty description."""
    text = _text(raw_text, DESCRIPTION_MAX)
    return BikeDescription(
        text=text,
        segments=[TextSegment(text=text, citations=list(sources))] if text else [],
        citations=sources if text else [],
    )


def build_details(company: str, model: str, data) -> BikeDetails:
    """The structured CLI answer -> BikeDetails (the backend's BikeDetailsResponse shape). Pure."""
    if not isinstance(data, dict):
        logger.error("details result is not an object | data=%r", data)
        return empty_details(company, model)
    if data.get("found") is False:
        # The model could not identify the bike: whatever it wrote (an apology, a note about
        # another model) is not data.
        logger.warning("model reports the bike was not found | company=%r model=%r", company, model)
        return empty_details(company, model)
    return BikeDetails(
        company=company,
        model=model,
        description=build_description(data.get("description"), _sources(data.get("sources"))),
        components=_components(data.get("components")),
        short_description=_text(data.get("short_description"), SHORT_DESCRIPTION_MAX),
    )


async def find_bike_details(company: str, model: str) -> BikeDetails:
    """One CLI details search. Raises SearcherError when the run fails; a run that found nothing
    is an unusable BikeDetails (no description, no components), not an error."""
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    user_message = f"Find the full details for: {' '.join(company.split())} {' '.join(model.split())}"
    t = time.perf_counter()
    try:
        data = await asyncio.to_thread(run_structured, system_prompt, user_message, DETAILS_SCHEMA)
    except ClaudeCliError as exc:
        raise searcher_error(exc) from exc
    details = build_details(company, model, data)
    logger.info(
        "details search done | company=%r model=%r description=%d short=%d elements=%d sources=%d elapsed=%.2fs",
        company, model, len(details.description.text), len(details.short_description),
        sum(len(s.elements) for c in details.components for s in c.subcategories),
        len(details.description.citations), time.perf_counter() - t,
    )
    if not is_usable_details(details):
        logger.warning("no usable details found | company=%r model=%r", company, model)
    return details
