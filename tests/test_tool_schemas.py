"""Эпик 04.09.2026 (3.3, AC-2.7) — схемы инструментов: имена, структура
JSON Schema (type/function/parameters), enum time_range, required.
"""
import json

from services.tool_schemas import (
    TOOL_CALLING_TOOLS,
    TOOL_EXECUTE_WEB_SEARCH,
    TOOL_QUERY_CHAT_MEMORY,
)


class TestToolSchemas:
    def test_two_tools_in_expected_order(self):
        assert [t["function"]["name"] for t in TOOL_CALLING_TOOLS] == [
            "execute_web_search", "query_chat_memory"]

    def _assert_function_schema(self, tool, name, required):
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] == name
        assert fn["description"].strip()
        params = fn["parameters"]
        assert params["type"] == "object"
        assert params["required"] == required
        assert params["additionalProperties"] is False
        # JSON-сериализуемость (отправляется в payload)
        json.dumps(tool)

    def test_execute_web_search_schema(self):
        self._assert_function_schema(
            TOOL_EXECUTE_WEB_SEARCH, "execute_web_search", ["query"])
        props = TOOL_EXECUTE_WEB_SEARCH["function"]["parameters"]["properties"]
        assert props["query"]["type"] == "string"

    def test_query_chat_memory_schema(self):
        self._assert_function_schema(
            TOOL_QUERY_CHAT_MEMORY, "query_chat_memory", ["query"])
        props = TOOL_QUERY_CHAT_MEMORY["function"]["parameters"]["properties"]
        assert props["query"]["type"] == "string"
        time_range = props["time_range"]
        assert time_range["enum"] == ["last_day", "last_week", "last_month", "all"]
        assert time_range["default"] == "all"

    def test_all_tools_list_is_mutable_snapshot(self):
        assert len(TOOL_CALLING_TOOLS) == 2
