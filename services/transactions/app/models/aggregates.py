from pydantic import BaseModel


class AggregateItem(BaseModel):
    currency: str
    category: str
    month: str
    total: str
    count: int


class AggregatesResponse(BaseModel):
    items: list[AggregateItem]
