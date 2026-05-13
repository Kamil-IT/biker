"""
Extracts product image URLs from an Allegro offer page.
Uses patchright (undetected Chromium) to render the page, regex-extracts allegroimg URLs,
then passes them through Claude for deduplication and ordering per the prompt rules.

Usage: python scripts/test_offer_images.py <offer_url>
Example: python scripts/test_offer_images.py https://allegro.pl/oferta/rower-mlodziezowy-indiana-rock-jr-24-cale-czarny-15516214705
"""
import json
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from anthropic import Anthropic  # noqa: E402
from patchright.sync_api import sync_playwright  # noqa: E402

PROMPTS_DIR = Path(__file__).parent.parent / "app" / "prompts"
MODEL = "claude-haiku-4-5-20251001"
_ALLEGRO_IMG_RE = re.compile(r"https://a\.allegroimg\.com/(?:original|s\d+)/[^\s\"'<>)\\]+")


def fetch_rendered_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pl-PL",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        # Warm up with the homepage so DataDome issues a valid session cookie
        page.goto("https://allegro.pl", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        # Fetch the actual offer page
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()
    return html


def extract_images_from_html(html: str) -> list[str]:
    raw = _ALLEGRO_IMG_RE.findall(html)
    urls: set[str] = set()
    for u in raw:
        clean = u.replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")
        urls.add(clean)
    return sorted(urls)


def extract_json_array(text: str) -> str:
    fence_start = text.find("```json")
    if fence_start != -1:
        after = text[fence_start + len("```json"):]
        fence_end = after.find("```")
        return (after[:fence_end] if fence_end != -1 else after).strip()
    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start != -1 and array_end != -1:
        return text[array_start:array_end + 1].strip()
    return text.strip()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_offer_images.py <offer_url>")
        sys.exit(1)

    offer_url = sys.argv[1]
    system_prompt = (PROMPTS_DIR / "allegro_image_extractor_prompt.md").read_text(encoding="utf-8")

    print(f"Fetching page: {offer_url}")
    html = fetch_rendered_html(offer_url)
    print(f"HTML length: {len(html)} chars")

    raw_images = extract_images_from_html(html)
    if not raw_images:
        print("No allegroimg URLs found in page HTML")
        sys.exit(1)

    print(f"Raw allegroimg URLs found: {len(raw_images)}")

    # Pass to Claude for deduplication, size preference, and gallery ordering
    client = Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": (
                f"Offer URL: {offer_url}\n\n"
                f"Image URLs found on the page:\n"
                + "\n".join(raw_images)
            ),
        }],
    )

    print(f"\nstop_reason: {response.stop_reason}")
    print(f"input_tokens: {response.usage.input_tokens}  output_tokens: {response.usage.output_tokens}\n")

    full_text = "".join(
        block.text for block in response.content if getattr(block, "type", None) == "text"
    )
    print("=== RAW RESPONSE ===")
    print(full_text)

    extracted = extract_json_array(full_text)
    print("\n=== EXTRACTED JSON ===")
    print(extracted)

    try:
        images = json.loads(extracted)
        assert isinstance(images, list), f"expected list, got {type(images).__name__}"
        print(f"\n=== IMAGE URLS ({len(images)}) ===")
        for url in images:
            print(url)
        print("\nOK")
    except (json.JSONDecodeError, AssertionError) as exc:
        print(f"\nFailed to parse image list: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
