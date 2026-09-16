"""Эпик 04.09.2026 (3.3, AC-2.7) — схемы инструментов: имена, структура
JSON Schema (type/function/parameters), enum time_range, required.

Раунд 9 (AGI Memory, T-820, spec §3.2.1/Q6): третий инструмент dig_into_lore;
порядок TOOL_CALLING_TOOLS = канону R9 (query_chat_memory → dig_into_lore →
execute_web_search); параметры query/year/person/mode (enum, default both).
"""
import json

from services.tool_schemas import (
    LORE_COMPILER_TOOL_NAME,
    TOOL_CALLING_TOOLS,
    TOOL_COMPILE_LORE_STORY,
    TOOL_DIG_INTO_LORE,
    TOOL_EXECUTE_WEB_SEARCH,
    TOOL_QUERY_CHAT_MEMORY,
    active_tools,
)


class TestToolSchemas:
    def test_eight_tools_in_expected_order(self):
        # Раунд 10.15 (F8, T-1611): канон R9 (память → лор → веб) + 4 новых
        # в конце; 10.20 (C/T-1887): +compile_lore_story → 8. Существующие
        # имена/схемы не меняются.
        assert [t["function"]["name"] for t in TOOL_CALLING_TOOLS] == [
            "query_chat_memory", "dig_into_lore", "execute_web_search",
            "summarize_video", "download_media", "get_bot_health",
            "get_recent_history", "compile_lore_story"]

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

    def test_dig_description_covers_fast_factual_routing(self):
        """10.20 (БЛОК 2.5, ADR-1020-2 п.4): роутинг-пара
        dig_into_lore ↔ compile_lore_story — dig EN-формулировка (дословно по
        ТЗ, стр. 55-56): fast/factual lookups, minimal precise facts."""
        desc = TOOL_DIG_INTO_LORE["function"]["description"]
        assert "fast, factual lookups" in desc
        assert "Who owns X?" in desc
        assert "When did Y happen?" in desc
        assert "minimal, precise facts" in desc
        assert TOOL_DIG_INTO_LORE["function"]["name"] == "dig_into_lore"

    def test_compile_lore_story_schema(self):
        """10.20 (C/T-1887, ТЗ стр. 56): 8-й инструмент — topic (required),
        EN-description дословно, additionalProperties=False."""
        self._assert_function_schema(
            TOOL_COMPILE_LORE_STORY, "compile_lore_story", ["topic"])
        props = TOOL_COMPILE_LORE_STORY["function"]["parameters"]["properties"]
        assert props["topic"]["type"] == "string"

    def test_compile_lore_story_description_verbatim(self):
        """EN-description — дословно по ТЗ (роутинг-пара с dig_into_lore)."""
        desc = TOOL_COMPILE_LORE_STORY["function"]["description"]
        assert desc == (
            "Use this ONLY when the user asks to explain a meme, tell a "
            "story, or give a comprehensive historical overview of a topic. "
            "Heavy narrative tool.")

    def test_active_tools_flag_on_off(self):
        """10.20 (О3/T-1887): ON (дефолт) — 8 инструментов; OFF — тул
        compile_lore_story недоступен, 7 прежних сохранены по именам."""
        assert [t["function"]["name"] for t in active_tools(True)] == [
            t["function"]["name"] for t in TOOL_CALLING_TOOLS]
        disabled = [t["function"]["name"] for t in active_tools(False)]
        assert disabled == [
            "query_chat_memory", "dig_into_lore", "execute_web_search",
            "summarize_video", "download_media", "get_bot_health",
            "get_recent_history"]
        assert LORE_COMPILER_TOOL_NAME not in disabled

    def test_active_tools_default_on(self):
        """О3: код-дефолт флага — ON (список без аргумента = 8 тулов)."""
        assert len(active_tools()) == 8

    def test_active_tools_does_not_mutate_snapshot(self):
        """active_tools возвращает новый список — снапшот не мутируется."""
        off = active_tools(False)
        assert len(off) == 7
        assert len(TOOL_CALLING_TOOLS) == 8

    # Bugfix 04.09.2026 (Часть 2, AC-3.4): расширенные description'ы.
    # 10.20 (БЛОК 7.4, T-1925): все description — EN (ревизия канона 3.3).
    def test_query_chat_memory_description_covers_count_questions(self):
        desc = TOOL_QUERY_CHAT_MEMORY["function"]["description"]
        assert "chat's history" in desc
        assert "Call FIRST" in desc
        assert "statistics" in desc
        assert "date range" in desc

    def test_execute_web_search_description_covers_fresh_data(self):
        desc = TOOL_EXECUTE_WEB_SEARCH["function"]["description"]
        assert "news" in desc
        assert "fresh" in desc
        assert "verification" in desc
        assert "memory" in desc

    def test_all_tools_list_is_mutable_snapshot(self):
        assert len(TOOL_CALLING_TOOLS) == 8
