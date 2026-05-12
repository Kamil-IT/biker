import logging
import time
from pathlib import Path

from anthropic import AsyncAnthropic

from .schemas import BikeDescription, DescriptionCitation, TextSegment

logger = logging.getLogger("biker.description")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

_FALLBACK = BikeDescription(text="", segments=[], citations=[])


async def find_bike_description(company: str, model: str) -> BikeDescription:
    system_prompt = (PROMPTS_DIR / "bike_description.md").read_text(encoding="utf-8")

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Describe the {company} {model} bicycle in 4–5 sentences."}],
    )
    elapsed = time.perf_counter() - t

    # Single pass: build per-fragment segments and global deduplicated citations
    seen_urls: set[str] = set()
    citations: list[DescriptionCitation] = []
    segments: list[TextSegment] = []

    for block in response.content:
        if getattr(block, "type", None) != "text":
            continue
        seg_citations: list[DescriptionCitation] = []
        for citation in getattr(block, "citations", None) or []:
            url = getattr(citation, "url", "").strip()
            if not url:
                continue
            dc = DescriptionCitation(
                url=url,
                title=str(getattr(citation, "title", "") or ""),
                cited_text=str(getattr(citation, "cited_text", "") or ""),
            )
            seg_citations.append(dc)
            if url not in seen_urls:
                seen_urls.add(url)
                citations.append(dc)
        segments.append(TextSegment(text=block.text, citations=seg_citations))

    text = "".join(s.text for s in segments).strip()

    if not text:
        logger.error("no text in description response")
        return _FALLBACK

    logger.info(
        "description done | elapsed=%.2fs input_tokens=%d output_tokens=%d segments=%d citations=%d\n%s",
        elapsed,
        response.usage.input_tokens,
        response.usage.output_tokens,
        len(segments),
        len(citations),
        text,
    )

    return BikeDescription(text=text, segments=segments, citations=citations)
