"""Utility tools: set_filter and export_transactions."""

import httpx
from tool_helpers import tool_by_name


class TestSetFilter:
    def test_returns_filter_set_event_with_provided_fields(self, build):
        tool = tool_by_name(build(lambda r: httpx.Response(200)), "set_filter")
        result = tool.func(currency="USD", min_amount="10")
        assert result == {"ui_event": "filter_set", "filter": {"currency": "USD", "min_amount": "10"}}

    def test_no_arguments_clears_filter(self, build):
        tool = tool_by_name(build(lambda r: httpx.Response(200)), "set_filter")
        result = tool.func()
        assert result == {"ui_event": "filter_set", "filter": {}}


class TestExportTransactions:
    def test_returns_export_ready_event(self, build):
        tool = tool_by_name(build(lambda r: httpx.Response(200)), "export_transactions")
        assert tool.func() == {"ui_event": "export_ready"}
