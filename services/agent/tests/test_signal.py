from app.signal import _nested_increment_dict, thread_field


class TestNestedIncrementDict:
    def test_single_flat_field(self):
        result = _nested_increment_dict(["transactions_version"])
        assert set(result.keys()) == {"transactions_version"}

    def test_dotted_field_becomes_nested(self):
        result = _nested_increment_dict(["thread_versions.abc-123"])
        assert "thread_versions" in result
        assert "abc-123" in result["thread_versions"]

    def test_empty_field_list_returns_empty_dict(self):
        assert _nested_increment_dict([]) == {}


class TestThreadField:
    def test_formats_dotted_path(self):
        assert thread_field("thread-1") == "thread_versions.thread-1"
