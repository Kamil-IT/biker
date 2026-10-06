from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class SearchRequest(BaseModel):
    search:               Optional[str]  = None
    brand:                Optional[str]  = None
    model:                Optional[str]  = None
    year:                 Optional[int]  = None
    wheel_size:           Optional[str]  = None
    is_electric:          Optional[bool] = None
    # Structured filters (TODO-003)
    bike_type:            Optional[str]  = None
    frame_size:           Optional[str]  = None

    @field_validator(
        "search", "brand", "model", "wheel_size",
        "bike_type", "frame_size",
        mode="before",
    )
    @classmethod
    def strip_and_none(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("year", mode="before")
    @classmethod
    def validate_year(cls, v):
        if v is None:
            return None
        y = int(v)
        if not (1900 <= y <= 2100):
            raise ValueError("year must be between 1900 and 2100")
        return y

    @model_validator(mode="after")
    def at_least_one_field(self) -> "SearchRequest":
        if not any(v is not None for v in [
            self.search, self.brand, self.model, self.year,
            self.wheel_size, self.is_electric,
            self.bike_type, self.frame_size,
        ]):
            raise ValueError("Provide at least one search field")
        return self

    def enriched_query(self) -> str:
        parts: list[str] = []
        if self.brand:              parts.append(f"Brand: {self.brand}")
        if self.model:              parts.append(f"Model: {self.model}")
        if self.year is not None:   parts.append(f"Year: {self.year}")
        if self.bike_type:          parts.append(f"Type: {self.bike_type}")
        if self.wheel_size:         parts.append(f"Wheel size: {self.wheel_size}")
        if self.frame_size:         parts.append(f"Frame size: {self.frame_size}")
        if self.is_electric is not None:
            parts.append(f"Electric: {'yes' if self.is_electric else 'no'}")
        prefix = ", ".join(parts)
        if prefix and self.search:
            return f"{prefix} — {self.search}"
        return prefix or self.search or ""


class BikeDetailsRequest(BaseModel):
    # Bounded to the bike.brand / bike.model column width: /v1/bike/details/search
    # forwards both into the searcher's CLI prompt and its bike row (TODO-041).
    company: str = Field(max_length=255)
    model: str = Field(max_length=255)

    @field_validator("company", "model")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


MISSING_TYPE_MAX_LEN = 64


class MissingDataRequest(BaseModel):
    company: str
    model: str
    missing_type: str  # free string — the enum lives in the frontend (TODO-027)

    @field_validator("company", "model")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("missing_type")
    @classmethod
    def bounded_type(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("missing_type must not be empty")
        if len(v) > MISSING_TYPE_MAX_LEN:
            raise ValueError(f"missing_type must be at most {MISSING_TYPE_MAX_LEN} characters")
        return v


class MissingDataResponse(BaseModel):
    bike_id: Optional[int]  # None when the bike is not in the `bike` table
    missing_type: str
    counter: int  # 0 when nothing was recorded


class PopularBike(BaseModel):
    """One curated home-page bike (TODO-034): the `bike` row's casing + a short blurb."""
    brand: str
    model: str
    category: Optional[str] = None  # bike.category, None = unknown
    description: str = ""  # first two sentences of the stored details description; "" without details


class PopularBikesResponse(BaseModel):
    bikes: list[PopularBike] = []


class SpecItem(BaseModel):
    key: str
    value: str


class ComponentElement(BaseModel):
    name: str
    description: str = ""
    specs: list[SpecItem] = []
    # TODO-042: the equipment row this bike element was searched as (bike trees only).
    equipment_id: Optional[int] = None
    # ISSUE-016: True when `name` is a specific product the UI may link to the
    # equipment view; False for "None included", paperwork and generic parts.
    # Stored per row in bike_component.is_linkable (bike trees only).
    is_linkable: bool = True


class BikeSubcategory(BaseModel):
    subcategory: str
    elements: list[ComponentElement] = []


class BikeCategory(BaseModel):
    category: str
    subcategories: list[BikeSubcategory] = []


class DescriptionCitation(BaseModel):
    url: str
    title: str
    cited_text: str


class TextSegment(BaseModel):
    text: str
    citations: list[DescriptionCitation] = []


class BikeDescription(BaseModel):
    text: str
    segments: list[TextSegment]
    citations: list[DescriptionCitation]


class BikeDetailsResponse(BaseModel):
    company: str
    model: str
    description: BikeDescription
    components: list[BikeCategory]
    short_description: str = ""
    category: Optional[str] = None


class BikeResult(BaseModel):
    brand: str
    model: str
    accessories: list[str]
    explanation: str
    category: Optional[str] = None


class BikeSearchResponse(BaseModel):
    search: str
    bikes: list[BikeResult]


class BikeReviewRequest(BaseModel):
    # Bounded to the bike.brand / bike.model column width: /v1/bike/review/search
    # forwards both into the searcher's CLI prompt and its bike row (TODO-037).
    company: str = Field(max_length=255)
    model: str = Field(max_length=255)

    @field_validator("company", "model")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class BikeReviewResponse(BaseModel):
    score: int
    explanation: str
    ref: list[str]
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

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, v: list[str]) -> list[str]:
        return v


class BikeOffer(BaseModel):
    brand: str
    model: str
    price: str
    is_new: bool
    url: str
    photos: list[str] = []
    source: str
    city: str | None = None


class BikeOfferRequest(BaseModel):
    # Bounded to the bike.brand / bike.model column width: /v1/bike/decathlon/search
    # forwards both into the searcher's CLI prompt and its bike row (TODO-032).
    company: str = Field(max_length=255)
    model: str = Field(max_length=255)

    @field_validator("company", "model")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class BikeOfferResponse(BaseModel):
    offers: list[BikeOffer]
    info: str = ""


class UsedBikeRequest(BaseModel):
    # Bounded to the bike.brand / bike.model column width: /v1/bike/used/search
    # forwards both into the searcher's CLI prompt and its bike row (TODO-031).
    company: str = Field(max_length=255)
    model: str = Field(max_length=255)

    @field_validator("company", "model")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class UsedBikeResponse(BaseModel):
    offers: list[BikeOffer]
    info: str = ""


class BikePhotosRequest(BaseModel):
    # Bounded to the bike.brand / bike.model column width: /v1/bike/photos/search
    # forwards both into the searcher's CLI prompt and its bike row.
    company: str = Field(max_length=255)
    model: str = Field(max_length=255)

    @field_validator("company", "model")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class BikePhotosResponse(BaseModel):
    photos: list[str] = []


class EquipmentDetailsRequest(BaseModel):
    """Read of stored equipment data (TODO-042): by `equipment_id` when given, else by name.

    The name lookup (TODO-044) matches the Python-normalised "company model"
    against `equipment.name_norm` (just the model when company is empty - the
    spec-tree click) or the researched (company_norm, model_norm) pair, and
    ignores `category` (the oldest matching row wins). `model` is bounded by
    the equipment.model / element_name column width (512).
    """
    company: str = Field(default="", max_length=255)
    model: str = Field(max_length=512)
    category: Optional[str] = Field(default=None, max_length=32)
    equipment_id: Optional[int] = Field(default=None, ge=1, le=2147483647)  # INTEGER range: no DB overflow

    @field_validator("company", mode="before")
    @classmethod
    def strip_company(cls, v):
        return str(v).strip() if v is not None else ""

    @field_validator("category", mode="before")
    @classmethod
    def strip_category(cls, v):
        return str(v).strip() if v is not None else None

    @field_validator("model")
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model must not be empty")
        return v.strip()

    @field_validator("category", mode="after")
    @classmethod
    def empty_category_to_none(cls, v):
        return v or None


class EquipmentDetailsResponse(BaseModel):
    company: str
    model: str
    category: str
    description: BikeDescription
    components: list[BikeCategory]
    short_description: str = ""
    equipment_id: Optional[int] = None


class EquipmentPhotosRequest(EquipmentDetailsRequest):
    """Same lookup as EquipmentDetailsRequest: by `equipment_id`, else by name."""


class EquipmentPhotosResponse(BaseModel):
    photos: list[str] = []
    equipment_id: Optional[int] = None


class EquipmentSearchRequest(BaseModel):
    """On-demand equipment search from a bike's spec tree (TODO-042).

    Bounded because every field reaches the searcher's CLI prompt and its rows.
    """
    bike_company: str = Field(max_length=255)
    bike_model: str = Field(max_length=255)
    element_name: str = Field(max_length=255)
    category: Optional[str] = Field(default=None, max_length=32)

    @field_validator("bike_company", "bike_model", "element_name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("category", mode="before")
    @classmethod
    def blank_category_to_none(cls, v):
        if v is None:
            return None
        return str(v).strip() or None


class EquipmentReviewRequest(BaseModel):
    company: str = ""
    model: str

    @field_validator("company", mode="before")
    @classmethod
    def strip_company(cls, v):
        return str(v).strip() if v is not None else ""

    @field_validator("model")
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model must not be empty")
        return v.strip()


class EquipmentReviewResponse(BaseModel):
    score: int
    explanation: str
    ref: list[str]

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: int) -> int:
        return max(0, min(10, v))


class ParseRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be empty")
        return v.strip()


class ParseResponse(BaseModel):
    brand:           Optional[str]  = None
    model:           Optional[str]  = None
    year:            Optional[int]  = None
    wheel_size:      Optional[str]  = None
    is_electric:     Optional[bool] = None

    def is_empty(self) -> bool:
        """True when the extractor found nothing at all.

        Every field is Optional and defaults to None, so an all-None response
        means the free text carried no recognisable bike attribute. The route
        turns this into a 400 rather than handing the UI a payload that would
        silently populate no filters.
        """
        return all(v is None for v in self.model_dump().values())


