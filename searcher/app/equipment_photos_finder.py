"""Equipment photo search (TODO-042) — the bike photo search with the equipment prompt.

Same two steps and the same hardening as photos_finder (it calls
photos_finder.find_product_photos): one `claude -p` run with WebSearch only
under prompts/equipment_photos.md answers {"url": …} = the manufacturer
product page, the URL must be a public http(s) address, Playwright opens it
once behind the route guard and keeps ≤ 8 <img> URLs that pass the same
_IMG_SRC / _SKIP / is_safe_image_url filters. Nothing is duplicated here.
"""
from . import config
from .equipment_categories import display_name, resolve_category
from .equipment_details_finder import prompt_value
from .photos_finder import find_product_photos

PROMPT_FILE = config.PROMPTS_DIR / "equipment_photos.md"


def user_message(bike_company: str, bike_model: str, element_name: str, slug: str) -> str:
    bike = prompt_value(f"{bike_company} {bike_model}")
    return (
        f'Find the official product page URL for the bike component or equipment item "{prompt_value(element_name)}" '
        f'(category: {display_name(slug)}) on the manufacturer\'s website. It is a component listed on the "{bike}" '
        "bicycle's spec sheet — use the bike only as context to identify the item."
    )


async def find_equipment_photos(
    bike_company: str, bike_model: str, element_name: str, category: str | None,
) -> tuple[str, list[str], str]:
    """(category slug, photo URLs in page order, product page URL). Raises SearcherError when the
    CLI run fails; no product page / a failed scrape is (slug, [], url) — not an error."""
    slug = resolve_category("", element_name, category)
    photos, product_url = await find_product_photos(
        PROMPT_FILE, user_message(bike_company, bike_model, element_name, slug), f"equipment {element_name!r} ({slug})",
    )
    return slug, photos, product_url
