from typing import Optional
from pydantic import BaseModel, field_validator, model_validator


class SearchRequest(BaseModel):
    search:               Optional[str]  = None
    brand:                Optional[str]  = None
    model:                Optional[str]  = None
    year:                 Optional[int]  = None
    wheel_size:           Optional[str]  = None
    is_electric:          Optional[bool] = None
    has_suspension:       Optional[bool] = None
    is_kids:              Optional[bool] = None
    # Structured filters (TODO-003)
    bike_type:            Optional[str]  = None
    price_max:            Optional[int]  = None
    frame_size:           Optional[str]  = None
    rider_height_cm:      Optional[int]  = None
    gender:               Optional[str]  = None
    frame_material:       Optional[str]  = None
    brake_type:           Optional[str]  = None
    drivetrain:           Optional[str]  = None
    belt_drive:           Optional[bool] = None
    battery_capacity_wh:  Optional[int]  = None

    @field_validator(
        "search", "brand", "model", "wheel_size",
        "bike_type", "frame_size", "gender", "frame_material",
        "brake_type", "drivetrain",
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

    @field_validator("price_max", "rider_height_cm", "battery_capacity_wh", mode="before")
    @classmethod
    def empty_int_to_none(cls, v):
        if v is None or v == "":
            return None
        return int(v)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "SearchRequest":
        if not any(v is not None for v in [
            self.search, self.brand, self.model, self.year,
            self.wheel_size, self.is_electric, self.has_suspension, self.is_kids,
            self.bike_type, self.price_max, self.frame_size, self.rider_height_cm,
            self.gender, self.frame_material, self.brake_type, self.drivetrain,
            self.belt_drive, self.battery_capacity_wh,
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
        if self.rider_height_cm is not None:
            parts.append(f"Rider height: {self.rider_height_cm} cm")
        if self.price_max is not None:
            parts.append(f"Max price: {self.price_max} PLN")
        if self.gender:             parts.append(f"Gender: {self.gender}")
        if self.frame_material:     parts.append(f"Frame material: {self.frame_material}")
        if self.brake_type:         parts.append(f"Brakes: {self.brake_type}")
        if self.drivetrain:         parts.append(f"Drivetrain: {self.drivetrain}")
        if self.is_electric is not None:
            parts.append(f"Electric: {'yes' if self.is_electric else 'no'}")
        if self.battery_capacity_wh is not None:
            parts.append(f"Battery: {self.battery_capacity_wh} Wh")
        if self.has_suspension is not None:
            parts.append(f"Suspension: {'yes' if self.has_suspension else 'no'}")
        if self.belt_drive is not None:
            parts.append(f"Belt drive: {'yes' if self.belt_drive else 'no'}")
        if self.is_kids is not None:
            parts.append(f"Kids bike: {'yes' if self.is_kids else 'no'}")
        prefix = ", ".join(parts)
        if prefix and self.search:
            return f"{prefix} — {self.search}"
        return prefix or self.search or ""


class BikeDetailsRequest(BaseModel):
    company: str
    model: str

    @field_validator("company", "model")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


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
    photos: list[str] = []


class CategoryResult(BaseModel):
    category: str
    score: int
    explanation: str

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: int) -> int:
        return max(0, min(10, v))


class SearchResponse(BaseModel):
    search: str
    results: list[CategoryResult]


class BikeResult(BaseModel):
    brand: str
    model: str
    accessories: list[str]
    match_score: float
    explanation: str


class BikeSearchResponse(BaseModel):
    search: str
    bikes: list[BikeResult]


class BikeReviewRequest(BaseModel):
    company: str
    model: str

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

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: int) -> int:
        return max(0, min(10, v))

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
    company: str
    model: str

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
    company: str
    model: str

    @field_validator("company", "model")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class UsedBikeResponse(BaseModel):
    offers: list[BikeOffer]
    info: str = ""


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
    has_suspension:  Optional[bool] = None
    is_kids:         Optional[bool] = None


