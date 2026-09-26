"""Query params for the transactions service's filter set, shared by every tool that
filters (query, bulk delete, cross-currency total)."""

from ..models.tool_results import TransactionFilter


def filter_params(**fields: str | None) -> dict:
    """The set filters as query params: from_date/to_date become the service's
    from/to, and unset ones are left out."""
    return TransactionFilter(**fields).model_dump(by_alias=True, exclude_none=True)
