"""Equipment photo search (TODO-042) — the bike photo search with the equipment prompt.

Same two steps and the same hardening as photos_finder (it calls
photos_finder.find_product_photos): one `claude -p` run with WebSearch only
under prompts/equipment_photos.md answers {"url": …} = the manufacturer
product page, the URL must be a public http(s) address, Playwright opens it
once behind the route guard and keeps ≤ 8 <img> URLs that pass the same
_IMG_SRC / _SKIP / is_safe_image_url filters. Nothing is duplicated here.
"""
from . import config
from .equipment_categories import resolve_category
from .equipment_details_finder import build_user_message
from .photos_finder import find_product_photos

PROMPT_FILE = config.PROMPTS_DIR / "equipment_photos.md"


def user_message(
    bike_company: str, bike_model: str, element_name: str, slug: str, element_type: str | None = None,
) -> str:
    return build_user_message(
        "Find the official product page URL on the manufacturer's website for", bike_company, bike_model,
        element_name, element_type, slug, "use the bike only as context to identify the item.",
    )  # without a bike: build_user_message's catalogue sentence ("identify the exact product by its name.")


async def find_equipment_photos(
    bike_company: str, bike_model: str, element_name: str, category: str | None, element_type: str | None = None,
) -> tuple[str, list[str], str]:
    """(category slug, photo URLs in page order, product page URL). Raises SearcherError when the
    CLI run fails; no product page / a failed scrape is (slug, [], url) — not an error."""
    slug = resolve_category("", element_name, category)
    photos, product_url = await find_product_photos(
        PROMPT_FILE, user_message(bike_company, bike_model, element_name, slug, element_type),
        f"equipment {element_name!r} ({slug})",
    )
    return slug, photos, product_url
