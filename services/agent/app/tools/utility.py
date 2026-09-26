"""Pure UI-event tools — set_filter and export_transactions make no HTTP calls
themselves; the frontend re-queries the table / builds the export from the event
payload."""

from typing import Optional

from langchain_core.tools import BaseTool, tool

from ..models.tool_results import ExportReadyResult, FilterSetResult, TransactionFilter


def build_utility_tools() -> list[BaseTool]:
    @tool
    def set_filter(
        currency: Optional[str] = None,
        category: Optional[str] = None,
        type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        min_amount: Optional[str] = None,
        max_amount: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        """Set the transactions table's filter in the UI; the UI re-queries itself.
        description is a case-insensitive substring match. Call with no arguments to
        clear the filter, which resets the table to its default view of the last 30
        days."""
        filt = TransactionFilter(
            currency=currency,
            category=category,
            type=type,
            to=to_date,
            min_amount=min_amount,
            max_amount=max_amount,
            description=description,
            **{"from": from_date},
        )
        return FilterSetResult(filter=filt).model_dump(by_alias=True, exclude_none=True)

    @tool
    def export_transactions() -> dict:
        """Export the table's current view (whatever it's filtered to) to a CSV that
        the UI attaches to your reply; nothing downloads until the user clicks it. To
        export a different view, call set_filter first. Call this every time an export
        is asked for. End your reply with exactly: "You can download it by clicking
        the file below."
        """
        return ExportReadyResult().model_dump()

    return [set_filter, export_transactions]
