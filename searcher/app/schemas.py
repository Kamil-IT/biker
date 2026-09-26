"""Pydantic models for the searcher's HTTP API."""
from pydantic import BaseModel, Field, field_validator


class BikeOffer(BaseModel):
    """One stored marketplace offer — the shape the backend serves back from the DB.

    Two sources write it: olx.pl used listings (/v1/search/olx → /v1/bike/used/olx:
    is_new false, city from the listing, photos scraped) and decathlon.pl new
    offers (/v1/search/decathlon → /v1/bike/decathlon: is_new from the shop
    page, default true, no city, no photos). The defaults are the OLX ones.
    """

    brand: str
    model: str
    price: str
    is_new: bool = False
    url: str
    photos: list[str] = []
    source: str = "olx.pl"
    city: str | None = None


class SearchRequest(BaseModel):
    """The bike to search for. Bounded to the bike.brand / bike.model column width:
    both values go into the CLI prompt and, for an unknown bike, into a new bike row."""

    company: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)

    @field_validator("company", "model", mode="before")
    @classmethod
    def strip_whitespace(cls, v):
        # Strip first so that min_length=1 rejects "   " as well as "" (422).
        return v.strip() if isinstance(v, str) else v


class SearchResponse(BaseModel):
    offers: list[BikeOffer]
    info: str = ""
    bike_id: int | None = None  # the bike row the offers were stored under
    saved: int = 0              # bike_offer rows written for this search


class HealthResponse(BaseModel):
    status: str = "ok"
    claude_cli: str | None = None  # `claude --version` output, null when the CLI is missing
    database: bool = False         # SELECT 1 succeeded
