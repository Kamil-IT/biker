"""
Standalone prompt tester — calls Anthropic directly (no running server needed).
Usage: python scripts/bike_offer_allegro.py <brand> <model>
Example: python scripts/bike_offer_allegro.py INDIANA "Rock Jr 24"
"""
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from anthropic import Anthropic  # noqa: E402

PROMPTS_DIR = Path(__file__).parent.parent / "app" / "prompts"
MODEL = "claude-haiku-4-5-20251001"


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/bike_offer_allegro.py <brand> <model>")
        sys.exit(1)

    brand = sys.argv[1]
    model = sys.argv[2]

    system_prompt = (PROMPTS_DIR / "bike_offer_allegro.md").read_text(encoding="utf-8")
    user_message = f"Find current offers on allegro for: {brand} {model}"

    print(f"Sending request for: {brand} {model}\n")

    client = Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[
            {"role": "user", "content": user_message},
            # {"role": "assistant", "content": "```json"},
        ],
    )

    print(f"stop_reason: {response.stop_reason}")
    print(f"input_tokens: {response.usage.input_tokens}  output_tokens: {response.usage.output_tokens}\n")

    full_text = "".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    )
    print(full_text)

    start_marker = "```json"
    start = full_text.find(start_marker)
    if start != -1:
        after_start = full_text[start + len(start_marker):]
        end = after_start.find("```")
        extracted = (after_start[:end] if end != -1 else after_start).strip()
    else:
        extracted = full_text.strip()

    print("=== EXTRACTED JSON ===")
    print(extracted)


if __name__ == "__main__":
    main()
