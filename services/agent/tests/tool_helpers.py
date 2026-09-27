"""Helpers for the tool tests (test_tools_*.py)."""

from app.services import categorize as categorize_module


def tool_by_name(built, name):
    return next(t for t in built if t.name == name)


def stub_categorize(monkeypatch, categories: dict[str, str]) -> list:
    """Replaces the model-backed categorizer; returns the recorded (descriptions,
    corrections) calls."""
    calls: list = []

    async def fake(descriptions, corrections):
        calls.append((descriptions, corrections))

        return [categories.get(d, "other") for d in descriptions]

    monkeypatch.setattr(categorize_module, "categorize", fake)

    return calls
