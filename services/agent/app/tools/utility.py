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
        """Set the transactions table's filter in the UI (e.g. "show USD expenses over
        100 from last month", "show transactions with 'bagel' in the description").
        description is a case-insensitive substring match. Calls nothing downstream —
        the UI re-queries with this filter itself. To clear the filter (e.g. "clear
        the filter", "reset"), call this with every argument left unset — you must
        still call it; replying that the filter is cleared without calling this tool
        does nothing. Clearing resets the table to its default view, the last 30 days
        — not to every transaction ever, so don't tell the user it now shows
        "everything"/"all transactions"; say it's back to showing the last 30 days."""
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
        """Export the transactions table's current view to a CSV file (e.g. "export
        transactions", "export this view", "download as csv"). You MUST call this
        tool for every such request, even if you exported earlier in this
        conversation — there is no file until you call it THIS turn; saying you've
        exported without calling it produces no file at all and misleads the user.
        Takes no arguments — it always exports exactly what the table is currently
        filtered to, not a filter you construct; if the user wants a different filter
        exported, call set_filter first, then this. Does nothing itself — the UI
        builds the CSV and attaches it to your reply as a clickable file; it is NOT
        downloaded automatically. Your reply's last sentence must say exactly "You can
        download it by clicking the file below." — use that exact wording, don't
        paraphrase it, and don't say it's been downloaded or saved anywhere, since
        nothing happens until they click it."""
        return ExportReadyResult().model_dump()

    return [set_filter, export_transactions]
