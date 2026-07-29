"""DB saver service (port 9105) — the ONLY writer.

Goes through repository.save_bike_details so flattening, ordering and cascade
behaviour stay identical to the live /v1/bike/details path, then reads the row
back: save_bike_details swallows its own exceptions, so a clean return proves
nothing.

Run:  .venv/Scripts/python.exe -m uvicorn pipeline.db_saver:app --port 9105
"""
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from app.models import init_db
from app.repository import get_bike_details, save_bike_details
from app.schemas import (
    BikeCategory,
    BikeDescription,
    BikeDetailsResponse,
    BikeSubcategory,
    ComponentElement,
    SpecItem,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("pipeline.db_saver")

app = FastAPI(title="db-saver")
init_db()


class Aggregate(BaseModel):
    brand: str
    model: str
    description: str = ""
    components: list = []
    photos: list = []
    source_urls: list = []


def _to_response(agg: Aggregate) -> BikeDetailsResponse:
    return BikeDetailsResponse(
        company=agg.brand,
        model=agg.model,
        description=BikeDescription(text=agg.description, segments=[], citations=[]),
        components=[
            BikeCategory(
                category=c.get("category", ""),
                subcategories=[
                    BikeSubcategory(
                        subcategory=s.get("subcategory", ""),
                        elements=[
                            ComponentElement(
                                name=e.get("name") or "",
                                description=e.get("description") or "",
                                specs=[
                                    SpecItem(key=sp.get("key", "") or "", value=sp.get("value", "") or "")
                                    for sp in (e.get("specs") or [])
                                ],
                            )
                            for e in (s.get("elements") or [])
                        ],
                    )
                    for s in (c.get("subcategories") or [])
                ],
            )
            for c in agg.components
            if isinstance(c, dict)
        ],
        photos=agg.photos,
    )


@app.get("/health")
def health() -> dict:
    return {"service": "db_saver"}


@app.post("/save")
def save(agg: Aggregate) -> dict:
    if get_bike_details(agg.brand, agg.model) is not None:
        logger.info("skipped_fresh | %s %s", agg.brand, agg.model)
        return {"stored": True, "status": "skipped_fresh", "verified": True, "error": None}

    save_bike_details(agg.brand, agg.model, _to_response(agg))

    check = get_bike_details(agg.brand, agg.model)
    ok = check is not None and bool(check.components)
    result = {
        "stored": ok,
        "status": "stored" if ok else "failed",
        "verified": ok,
        "db_rows": {
            "bike_detail_component": sum(
                len(e.specs) or 1
                for c in (check.components if ok else [])
                for s in c.subcategories
                for e in s.elements
            ),
            "bike_detail_photos": len(check.photos) if ok else 0,
        },
        "error": None if ok else "read-back failed after save_bike_details",
    }
    logger.info("save | %s %s | %s", agg.brand, agg.model, result["status"])
    return result
