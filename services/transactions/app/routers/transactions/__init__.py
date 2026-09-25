from fastapi import APIRouter

router = APIRouter()

from . import create, delete, list, patch  # noqa: E402,F401 — registers routes on `router`
