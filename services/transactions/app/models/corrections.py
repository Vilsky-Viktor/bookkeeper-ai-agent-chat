from pydantic import BaseModel


class Correction(BaseModel):
    item_key: str  # normalized description
    category: str


class CorrectionsResponse(BaseModel):
    items: list[Correction]
