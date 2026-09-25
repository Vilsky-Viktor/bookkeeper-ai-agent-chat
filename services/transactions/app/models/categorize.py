from pydantic import BaseModel


class CategorizeRequest(BaseModel):
    description: str | None = None
    amount: str
    currency: str
    type: str = "expense"


class CategorizeResponse(BaseModel):
    category: str
