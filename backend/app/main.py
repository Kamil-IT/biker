import logging
import time
from dotenv import load_dotenv

load_dotenv()  # must run before anthropic_scorer imports AsyncAnthropic

from fastapi import FastAPI, HTTPException  # noqa: E402
from .schemas import SearchRequest, SearchResponse, CategoryResult  # noqa: E402
from .categories import BIKE_CATEGORIES, CATEGORY_PROMPTS  # noqa: E402
from .anthropic_scorer import score_category  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("biker.search")

app = FastAPI(title="Biker API", version="1.0.0")


@app.post("/v1/bike/search", response_model=SearchResponse)
async def bike_search(req: SearchRequest) -> SearchResponse:
    logger.info("search request received | query=%r", req.search)
    results: list[CategoryResult] = []
    t_total = time.perf_counter()

    for name, _ in BIKE_CATEGORIES:
        t_cat = time.perf_counter()
        logger.info("scoring category | category=%r", name)
        try:
            result = await score_category(req.search, name, CATEGORY_PROMPTS[name])
            elapsed = time.perf_counter() - t_cat
            logger.info(
                "category scored   | category=%-20s score=%2d  elapsed=%.2fs  explanation=%r",
                f"{name!r}",
                result.score,
                elapsed,
                result.explanation,
            )
            results.append(result)
        except Exception as exc:
            logger.error("scoring failed | category=%r error=%s", name, exc)
            raise HTTPException(
                status_code=502,
                detail=f"Upstream error for category {name!r}: {exc}",
            ) from exc

    results.sort(key=lambda r: r.score, reverse=True)
    total_elapsed = time.perf_counter() - t_total
    logger.info(
        "search complete | categories=%d top=%r score=%d total_elapsed=%.2fs",
        len(results),
        results[0].category if results else "n/a",
        results[0].score if results else 0,
        total_elapsed,
    )
    return SearchResponse(search=req.search, results=results)
