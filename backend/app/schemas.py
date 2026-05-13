from pydantic import BaseModel, field_validator


class SearchRequest(BaseModel):
    search: str

    @field_validator("search")
    @classmethod
    def search_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("search must not be empty")
        return v.strip()


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
    def single_ref(cls, v: list[str]) -> list[str]:
        return v[:1]


class BikeOffer(BaseModel):
    brand: str
    model: str
    price: str
    is_new: bool
    url: str
    photos: list[str] = []
    source: str


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


