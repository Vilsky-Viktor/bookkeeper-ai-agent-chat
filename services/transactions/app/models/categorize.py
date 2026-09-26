from pydantic import BaseModel, Field


class CategorizeRequest(BaseModel):
    description: str | None = None
    amount: str
    currency: str
    type: str = "expense"


class CategorizeResponse(BaseModel):
    category: str


class CategorizeBatchRequest(BaseModel):
    # Bounded so one request can't turn into an unbounded prompt.
    descriptions: list[str] = Field(min_length=1, max_length=100)


class CategorizeBatchResponse(BaseModel):
    categories: list[str]
