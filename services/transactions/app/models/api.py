from pydantic import BaseModel


class HealthzResponse(BaseModel):
    ok: bool
