"""Эпик 04.09.2026 (3.3, AC-2.7) — схемы инструментов: имена, структура
JSON Schema (type/function/parameters), enum time_range, required.

Раунд 9 (AGI Memory, T-820, spec §3.2.1/Q6): третий инструмент dig_into_lore;
порядок TOOL_CALLING_TOOLS = канону R9 (query_chat_memory → dig_into_lore →
execute_web_search); параметры query/year/person/mode (enum, default both).
"""
import json

from services.tool_schemas import (
    TOOL_CALLING_TOOLS,
    TOOL_DIG_INTO_LORE,
    TOOL_EXECUTE_WEB_SEARCH,
    TOOL_QUERY_CHAT_MEMORY,
)


class TestToolSchemas:
    def test_three_tools_in_expected_order(self):
        assert [t["function"]["name"] for t in TOOL_CALLING_TOOLS] == [
            "query_chat_memory", "dig_into_lore", "execute_web_search"]

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

    def test_dig_into_lore_schema(self):
        """Раунд 9 (spec §3.2.1/Q6): query (required), year int, person str,
        mode enum messages|facts|both default both."""
        self._assert_function_schema(
            TOOL_DIG_INTO_LORE, "dig_into_lore", ["query"])
        props = TOOL_DIG_INTO_LORE["function"]["parameters"]["properties"]
        assert props["query"]["type"] == "string"
        assert props["year"]["type"] == "integer"
        assert props["person"]["type"] == "string"
        mode = props["mode"]
        assert mode["enum"] == ["messages", "facts", "both"]
        assert mode["default"] == "both"

    def test_dig_description_covers_nostalgia_triggers(self):
        desc = TOOL_DIG_INTO_LORE["function"]["description"]
        for trigger in ("помнишь", "как мы тогда", "в 2024", "ПЕРВЫМ",
                        "год назад"):
            assert trigger in desc, trigger
        assert "year" in desc and "person" in desc

    # Bugfix 04.09.2026 (Часть 2, AC-3.4): расширенные description'ы.
    def test_query_chat_memory_description_covers_count_questions(self):
        desc = TOOL_QUERY_CHAT_MEMORY["function"]["description"]
        assert "сколько раз" in desc
        assert "ПЕРВЫМ" in desc
        assert "статистика" in desc
        assert "диапазон дат" in desc

    def test_execute_web_search_description_covers_fresh_data(self):
        desc = TOOL_EXECUTE_WEB_SEARCH["function"]["description"]
        assert "новости" in desc
        assert "свежие" in desc
        assert "проверка" in desc
        assert "в памяти" in desc

    def test_all_tools_list_is_mutable_snapshot(self):
        assert len(TOOL_CALLING_TOOLS) == 3
