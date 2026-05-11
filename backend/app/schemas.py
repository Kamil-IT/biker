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


class BikeDetailsResponse(BaseModel):
    company: str
    model: str
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
