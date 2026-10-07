import re
from typing import Annotated, Literal, Optional, get_args
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

# The contact form's "W jakiej sprawie?" choices. The slugs are stored; the Polish
# labels live in the frontend (ContactPage.tsx), like the search filters' options.
ContactTopic = Literal["missing_bike", "wrong_data", "feature_idea", "cooperation", "other"]
CONTACT_TOPICS = get_args(ContactTopic)
CONTACT_NAME_MAX_LEN = 100
CONTACT_EMAIL_MAX_LEN = 254
CONTACT_MESSAGE_MAX_LEN = 5000
# Deliberately loose (one @, a dot in the domain, no whitespace): the address is only
# used to reply by hand, so a typo costs a reply, not a broken feature.
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class ContactMessageRequest(BaseModel):
    """The "Napisz do nas" form of the Kontakt tab. Strings are trimmed; `name` is optional.

    `website` is a honeypot: the form hides it, so only a bot fills it in.
    """
    name: str = Field(default="", max_length=CONTACT_NAME_MAX_LEN)
    email: str = Field(max_length=CONTACT_EMAIL_MAX_LEN)
    topic: ContactTopic
    message: str = Field(min_length=1, max_length=CONTACT_MESSAGE_MAX_LEN)
    website: str = ""

    @field_validator("name", "email", "message", "website", mode="before")
    @classmethod
    def strip(cls, v):
        # NUL is dropped too: PostgreSQL refuses it in a text column.
        return v.replace("\x00", "").strip() if isinstance(v, str) else v

    @field_validator("email")
    @classmethod
    def email_shape(cls, v: str) -> str:
        if not _EMAIL_RE.fullmatch(v):
            raise ValueError("not a valid e-mail address")
        return v


class ContactMessageResponse(BaseModel):
    ok: bool = True


# Frame-size calculator (TODO-045). The bike types are a subset of the future BIKE_CATEGORIES
# keys; the limits below bound what the formulas in app/frame_size.py were built for.
FitBikeType = Literal["Road", "MTB", "Gravel", "Touring", "Hybrid/Commuter"]
FIT_BIKE_TYPES = get_args(FitBikeType)
FrameLetter = Literal["XS", "S", "M", "L", "XL"]
FIT_HEIGHT_MIN_CM, FIT_HEIGHT_MAX_CM = 140, 210
FIT_INSEAM_MIN_CM, FIT_INSEAM_MAX_CM = 60, 110


class FrameSizeRequest(BaseModel):
    """Rider measurements + bike type for POST /v1/fit/frame-size. Out of range, NaN/inf or an unknown type is a 422."""
    height_cm: float = Field(ge=FIT_HEIGHT_MIN_CM, le=FIT_HEIGHT_MAX_CM, allow_inf_nan=False)
    inseam_cm: float = Field(ge=FIT_INSEAM_MIN_CM, le=FIT_INSEAM_MAX_CM, allow_inf_nan=False)
    bike_type: FitBikeType


class FrameSizeResponse(BaseModel):
    bike_type: FitBikeType
    size: float  # the formula's result, 1 decimal, in `unit`
    unit: Literal["cm", "in"]  # "in" for MTB
    range_min: float
    range_max: float
    letter: FrameLetter  # the letter of `size` (main recommendation)
    letters: list[FrameLetter]  # every letter from range_min's to range_max's, ascending (1-3 items)
    confidence: Literal["good", "medium"]
    measurement_warning: bool  # inseam / height outside 0.40-0.50 — the inseam was probably measured wrong


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
    id: Optional[int] = None  # bike.id — the frontend's /bike/{id} address
    brand: str
    model: str
    category: Optional[str] = None  # bike.category, None = unknown
    description: str = ""  # first two sentences of the stored details description; "" without details
    photo: Optional[str] = None  # cover photo URL (first stored photo that is not junk); None = no photo
    photo_bg: Optional[str] = None  # "#RRGGBB" edge colour of that photo; None = unknown


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
    # bike.id — the frontend's /bike/{id} address; None only when the bike row is missing
    # (a swallowed save_search failure on the AI path).
    id: Optional[int] = None
    brand: str
    model: str
    accessories: list[str]
    explanation: str
    category: Optional[str] = None
    photo: Optional[str] = None  # cover photo URL (first stored photo that is not junk); None = no photo
    photo_bg: Optional[str] = None  # "#RRGGBB" edge colour of that photo; None = unknown


DbId = Annotated[int, Field(ge=1, le=2147483647)]  # INTEGER range: no DB overflow


class BikeByIdRequest(BaseModel):
    """POST /v1/bike/by-id: one bike by its id (the frontend's /bike/{id} deep link)."""
    bike_id: DbId


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
    the equipment.model / element_name column width (512); it may be empty when
    `equipment_id` is given (the /equipment/{id} deep link knows only the id).
    """
    company: str = Field(default="", max_length=255)
    model: str = Field(default="", max_length=512)
    category: Optional[str] = Field(default=None, max_length=32)
    equipment_id: Optional[DbId] = None

    @field_validator("company", "model", mode="before")
    @classmethod
    def strip_text(cls, v):
        return str(v).strip() if v is not None else ""

    @field_validator("category", mode="before")
    @classmethod
    def strip_category(cls, v):
        return str(v).strip() if v is not None else None

    @model_validator(mode="after")
    def model_or_id(self) -> "EquipmentDetailsRequest":
        if not self.model and self.equipment_id is None:
            raise ValueError("model must not be empty")
        return self

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

    Either by `equipment_id` (+ optional `bike_id`, the bike the view was opened
    from — the context bike; else the first bike linked to the item) or by
    `bike_company` + `bike_model` + `element_name`. Bounded because every field
    reaches the searcher's CLI prompt and its rows.
    """
    bike_company: str = Field(default="", max_length=255)
    bike_model: str = Field(default="", max_length=255)
    element_name: str = Field(default="", max_length=255)
    category: Optional[str] = Field(default=None, max_length=32)
    equipment_id: Optional[DbId] = None
    bike_id: Optional[DbId] = None

    @field_validator("bike_company", "bike_model", "element_name", mode="before")
    @classmethod
    def strip(cls, v):
        return str(v).strip() if v is not None else ""

    @model_validator(mode="after")
    def by_id_or_by_name(self) -> "EquipmentSearchRequest":
        if self.equipment_id is None and not (self.bike_company and self.bike_model and self.element_name):
            raise ValueError("give equipment_id, or bike_company + bike_model + element_name (must not be empty)")
        return self

    @field_validator("category", mode="before")
    @classmethod
    def blank_category_to_none(cls, v):
        if v is None:
            return None
        return str(v).strip() or None


class EquipmentByIdRequest(BaseModel):
    """POST /v1/equipment/by-id: one equipment item by its id (the frontend's /equipment/{id})."""
    equipment_id: DbId


class BikeRef(BaseModel):
    id: int
    brand: str
    model: str


class EquipmentItemResponse(BaseModel):
    """Identity of one equipment item + the first bike whose spec tree links it (the back target)."""
    equipment_id: int
    name: str  # the element name it was opened as
    category: str
    company: str  # researched brand, "" until a details search filled it
    model: str
    bike: Optional[BikeRef] = None


class EquipmentResolveRequest(BaseModel):
    """POST /v1/equipment/resolve: the equipment row of one element of a bike's spec tree."""
    bike_id: DbId
    element_name: str = Field(max_length=512)  # bike_component.element_name width

    @field_validator("element_name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class EquipmentResolveResponse(BaseModel):
    equipment_id: int
    name: str
    category: str


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
    # One of bike_categories.SEARCH_BIKE_TYPES (the form's "Typ roweru" values) or None.
    bike_type:       Optional[str]  = None

    def is_empty(self) -> bool:
        """True when the extractor found nothing at all.

        Every field is Optional and defaults to None, so an all-None response
        means the free text carried no recognisable bike attribute. The route
        turns this into a 400 rather than handing the UI a payload that would
        silently populate no filters.
        """
        return all(v is None for v in self.model_dump().values())


