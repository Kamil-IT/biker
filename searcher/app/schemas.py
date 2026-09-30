"""Pydantic models for the searcher's HTTP API."""
from pydantic import BaseModel, Field, field_validator


class BikeOffer(BaseModel):
    """One stored marketplace offer — the shape the backend serves back from the DB.

    Three sources write it: olx.pl used listings (/v1/search/olx → /v1/bike/used/olx:
    is_new false, city from the listing, photos scraped), decathlon.pl new
    offers (/v1/search/decathlon → /v1/bike/decathlon: is_new from the shop
    page, default true, no city, no photos) and allegro.pl offers
    (/v1/search/allegro → /v1/bike/allegro: is_new from the search result,
    default false, no city, no photos — allegro.pl answers 403 to browsers). The defaults are the OLX ones.
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


class PhotosResponse(BaseModel):
    photos: list[str]           # the bike's photo URLs in display order — stored ones or the new ones
    bike_id: int | None = None  # the bike row the photos belong to (null: unknown bike, nothing found)
    saved: int = 0              # bike_detail_photos rows written by this call (0 when returned from the DB)


class BikeReview(BaseModel):
    """A bike's expert review — the backend's BikeReviewResponse shape, same clamps.

    The empty review (all defaults) means "nothing found / nothing stored".
    """

    score: int = 0
    explanation: str = ""
    ref: list[str] = []
    rating: float = 0.0
    sources_used: int = 0

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: int) -> int:
        return max(0, min(10, v))

    @field_validator("rating")
    @classmethod
    def clamp_rating(cls, v: float) -> float:
        return round(max(0.0, min(10.0, float(v))), 1)

    @field_validator("sources_used")
    @classmethod
    def clamp_sources(cls, v: int) -> int:
        return max(0, int(v))


class ReviewResponse(BaseModel):
    review: BikeReview          # the review now stored for the bike (see /v1/search/review)
    bike_id: int | None = None  # the bike row the review belongs to (null: unknown bike, nothing stored)
    saved: int = 0              # 1 when this call wrote the review, else 0


class SpecItem(BaseModel):
    key: str
    value: str


class ComponentElement(BaseModel):
    name: str
    description: str = ""
    specs: list[SpecItem] = []


class BikeSubcategory(BaseModel):
    subcategory: str
    elements: list[ComponentElement] = []


class BikeCategory(BaseModel):
    category: str
    subcategories: list[BikeSubcategory] = []


class DescriptionCitation(BaseModel):
    url: str
    title: str
    cited_text: str = ""


class TextSegment(BaseModel):
    text: str
    citations: list[DescriptionCitation] = []


class BikeDescription(BaseModel):
    text: str = ""
    segments: list[TextSegment] = []
    citations: list[DescriptionCitation] = []


class BikeDetails(BaseModel):
    """The backend's BikeDetailsResponse shape (TODO-041). All-default description/components = nothing found."""

    company: str
    model: str
    description: BikeDescription = BikeDescription()
    components: list[BikeCategory] = []
    short_description: str = ""


class DetailsResponse(BaseModel):
    details: BikeDetails        # the details now stored for the bike (or what this run found when nothing was stored)
    bike_id: int | None = None  # the bike row the details belong to (null: unknown bike, nothing stored)
    saved: int = 0              # 1 when this call wrote the details, else 0


class HealthResponse(BaseModel):
    status: str = "ok"
    claude_cli: str | None = None  # `claude --version` output, null when the CLI is missing
    database: bool = False         # SELECT 1 succeeded
