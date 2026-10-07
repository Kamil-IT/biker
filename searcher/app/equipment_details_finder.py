"""Equipment details search (TODO-042) — description, short description and the spec tree in ONE CLI run.

Replaces the backend's two Anthropic SDK calls (equipment_details_finder's
per-category component call + equipment_description_finder) with one
`claude -p` turn (WebSearch + WebFetch, no Playwright, subscription-billed).
The system prompt is prompts/equipment_details.md (role, budget, Polish
description rules, `found`, sources rule) followed by the category part
prompts/equipment_details_{slug}.md (subcategories + example). The answer is
validated against the bike details schema (same keys), and the bike helpers
build the description and parse the tree. build_equipment_details() is pure.

The item comes from a bike's spec tree, so it is identified by its element
name (company ""), and the bike is named in the user message as context only.
build_user_message() (pure, shared with the photo search) adds the element type
(its subcategory on the spec sheet) and, for an element named exactly like the
bike — typically the frame — says it is that part of the bike, not the bike.
"""
import asyncio
import logging
import re
import time

from . import config
from .claude_cli import ClaudeCliError, run_structured
from .details_finder import (
    DETAILS_SCHEMA,
    ELEMENT_NAME_MAX,
    SHORT_DESCRIPTION_MAX,
    _sources,
    _text,
    build_description,
    is_usable_details,
    parse_categories,
)
from .equipment_categories import EQUIPMENT_PROMPTS, display_name, resolve_category
from .olx_finder import searcher_error
from .schemas import BikeCategory, DescriptionCitation, EquipmentDetails
from .shop_filter import is_shop_source

logger = logging.getLogger("searcher.equipment.details")

COMMON_PROMPT_FILE = config.PROMPTS_DIR / "equipment_details.md"
COMPANY_MAX = 255  # equipment.company column width
# The bike details answer plus the identified product (TODO-044): `company` (the manufacturer / brand, "" when
# unknown) and `model` (the model name WITHOUT the brand, "" when unknown). A copy - the bike schema is unchanged.
EQUIPMENT_DETAILS_SCHEMA = {
    **DETAILS_SCHEMA,
    "properties": {**DETAILS_SCHEMA["properties"], "company": {"type": "string"}, "model": {"type": "string"}},
    "required": [*DETAILS_SCHEMA["required"], "company", "model"],
}

def _no_shops(sources: list[DescriptionCitation], item_name: str) -> list[DescriptionCitation]:
    """Drop shop / marketplace sources (shop_filter); an all-dropped list leaves the description as it is."""
    kept = [s for s in sources if not is_shop_source(s.url, item_name)]
    if len(kept) < len(sources):
        logger.info("equipment sources: %d shop link(s) dropped | %s", len(sources) - len(kept),
                    [s.url for s in sources if s not in kept])
    return kept


SHORT_DESCRIPTION_CAP = 400
_LABEL = re.compile(r"^\s*(?:short[ _]description|description|krótki opis|opis)\s*:\s*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")


def clean_short_description(raw) -> str:
    """The 2-sentence summary only. A probe got "<2 sentences>\\n\\nDescription: <whole description>" for
    apparel, so: keep the part before the first blank line, strip a leading "Description:"-style label,
    cap at SHORT_DESCRIPTION_CAP characters cut at the last sentence end inside the cap."""
    text = _text(raw, SHORT_DESCRIPTION_MAX)
    text = _LABEL.sub("", text.split("\n\n", 1)[0]).strip()
    if len(text) <= SHORT_DESCRIPTION_CAP:
        return text
    head = text[:SHORT_DESCRIPTION_CAP]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    return (head[:ends[-1]] if ends else head).strip()


def _tree(raw, slug: str) -> list[BikeCategory]:
    """Every subcategory the model returned, under ONE category named after the item's category; [] when empty."""
    subcategories = [sub for cat in parse_categories(raw) for sub in cat.subcategories]
    return [BikeCategory(category=display_name(slug), subcategories=subcategories)] if subcategories else []


def empty_equipment_details(element_name: str, slug: str) -> EquipmentDetails:
    return EquipmentDetails(company="", model=element_name, category=slug)


def build_equipment_details(element_name: str, slug: str, data) -> EquipmentDetails:
    """The structured CLI answer -> EquipmentDetails (company "", model = element name; what the run identified
    as the manufacturer / model goes to found_company / found_model). Pure."""
    if not isinstance(data, dict):
        logger.error("equipment details result is not an object | data=%r", data)
        return empty_equipment_details(element_name, slug)
    if data.get("found") is False:
        logger.warning("model reports the item was not found | element=%r category=%r", element_name, slug)
        return empty_equipment_details(element_name, slug)
    return EquipmentDetails(
        company="",
        model=element_name,
        category=slug,
        description=build_description(data.get("description"), _no_shops(_sources(data.get("sources")), element_name)),
        components=_tree(data.get("components"), slug),
        short_description=clean_short_description(data.get("short_description")),
        found_company=_text(data.get("company"), COMPANY_MAX),
        found_model=_text(data.get("model"), ELEMENT_NAME_MAX),
    )


def system_prompt(slug: str) -> str:
    return COMMON_PROMPT_FILE.read_text(encoding="utf-8") + "\n\n" + EQUIPMENT_PROMPTS[slug]


# Characters a client-supplied name could use to break out of its quotes in the prompt: double quotes (ASCII and
# typographic), backticks, C0/C1 control characters (newlines included) and the Unicode line/paragraph separators.
_PROMPT_UNSAFE = re.compile("[\"\u201c\u201d\u201e\u201f`\x00-\x1f\x7f-\x9f\u2028\u2029]")


def prompt_value(value: str) -> str:
    """A client-supplied name made safe to embed in quotes: unsafe characters -> spaces, whitespace collapsed."""
    return " ".join(_PROMPT_UNSAFE.sub(" ", value or "").split())


def _norm_name(value: str) -> str:
    """strip + lower + collapse whitespace (after prompt_value), for the "named after the bike" check."""
    return " ".join(prompt_value(value).lower().split())


def is_named_after_bike(bike_company: str, bike_model: str, element_name: str) -> bool:
    """True when the element carries the bike's own name ("Giant" "Revolt Advanced Pro" ->
    "Giant Revolt Advanced Pro" or "Revolt Advanced Pro") — on a spec sheet that is the frame.
    Always False without a bike (a catalogue part, TODO-046)."""
    name = _norm_name(element_name)
    if not name or not _norm_name(bike_model):
        return False
    return name in (_norm_name(f"{bike_company} {bike_model}"), _norm_name(bike_model))


def build_user_message(
    task: str, bike_company: str, bike_model: str, element_name: str, element_type: str | None, slug: str,
    context: str, catalogue_context: str = "identify the exact product by its name.",
) -> str:
    """The equipment searches' user message. Pure.

    `task` opens it ("Find the specifications and an overview of"), `context` follows the bike
    sentence. A given element type is named ((listed under "Frame" on the spec sheet)); an
    element carrying the bike's own name gets a sentence saying it is that part of the bike
    (the frame when the type is unknown), so the model does not answer found: false for "not
    a component". Without a bike (a catalogue part from the parts search, TODO-046) there is
    no bike sentence: the element type is the part type ("Cassette") and `catalogue_context`
    follows. Every client-supplied value goes through prompt_value.
    """
    bike = prompt_value(f"{bike_company} {bike_model}")
    kind = prompt_value(element_type or "")
    if not prompt_value(bike_model):
        typed = f' (part type: "{kind}")' if kind else ""
        return (
            f'{task} the bike component or equipment item "{prompt_value(element_name)}"{typed} '
            f"(category: {display_name(slug)}). It comes from a bicycle parts catalogue, not from a bike's "
            f"spec sheet — {catalogue_context}"
        )
    listed = f' (listed under "{kind}" on the spec sheet)' if kind else ""
    message = (
        f'{task} the bike component or equipment item "{prompt_value(element_name)}"{listed} '
        f'(category: {display_name(slug)}). It is a component listed on the "{bike}" bicycle\'s spec sheet — {context}'
    )
    if is_named_after_bike(bike_company, bike_model, element_name):
        part = kind or "frame"
        message += (
            f" This element carries the bike's own name: it is the {part} of that bike (for a frame: the frameset "
            "sold or documented by the bike maker), not the complete bike. Describe that part. When the bike maker "
            "documents it, answer found: true."
        )
    return message


def user_message(
    bike_company: str, bike_model: str, element_name: str, slug: str, element_type: str | None = None,
) -> str:
    return build_user_message(
        "Find the specifications and an overview of", bike_company, bike_model, element_name, element_type, slug,
        "use the bike only as context to identify the item (for a generic name, the version fitted to that bike). "
        "When the manufacturer documents the part, answer found: true.",
        "identify the exact product by its name (maker and model code). "
        "When the manufacturer documents the part, answer found: true.",
    )


async def find_equipment_details(
    bike_company: str, bike_model: str, element_name: str, category: str | None, element_type: str | None = None,
) -> tuple[str, EquipmentDetails]:
    """(category slug, what the run found). Raises SearcherError when the run fails; a run that found
    nothing is an unusable EquipmentDetails (no description, no components), not an error."""
    slug = resolve_category("", element_name, category)
    t = time.perf_counter()
    try:
        data = await asyncio.to_thread(
            run_structured, system_prompt(slug),
            user_message(bike_company, bike_model, element_name, slug, element_type),
            EQUIPMENT_DETAILS_SCHEMA,
        )
    except ClaudeCliError as exc:
        raise searcher_error(exc) from exc
    details = build_equipment_details(element_name, slug, data)
    logger.info(
        "equipment details search done | element=%r type=%r category=%r bike=%r %r description=%d short=%d "
        "elements=%d sources=%d elapsed=%.2fs",
        element_name, element_type, slug, bike_company, bike_model, len(details.description.text), len(details.short_description),
        sum(len(s.elements) for c in details.components for s in c.subcategories),
        len(details.description.citations), time.perf_counter() - t,
    )
    if not is_usable_details(details):
        logger.warning("no usable equipment details found | element=%r category=%r", element_name, slug)
    return slug, details
