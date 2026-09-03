"""Эпик 04.09.2026 (3.3, Часть 2) — JSON Schema инструментов Tool Calling.

Используются в цикле services/tool_loop.py для direct_chat (FR-17: только
direct_chat получает инструменты). Имена/схемы — канон 3.3 (не менять без
ревизии spec: модели опираются на description при выборе инструмента).
"""

TOOL_EXECUTE_WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "execute_web_search",
        "description": "Поиск в интернете (каскад Tavily→Exa→DuckDuckGo). "
                       "Вызывай, когда ответу нужны свежие/внешние факты, которых нет в контексте.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Поисковый запрос (короткий, по-русски или по-английски)."}
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

TOOL_QUERY_CHAT_MEMORY = {
    "type": "function",
    "function": {
        "name": "query_chat_memory",
        "description": "Поиск по памяти бота: истории этого чата и долгосрочным фактам. "
                       "Вызывай, когда спрашивают «что я говорил/что было раньше/помнишь ли».",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "О чём вспомнить."},
                "time_range": {
                    "type": "string",
                    "enum": ["last_day", "last_week", "last_month", "all"],
                    "description": "Окно времени: last_day/last_week/last_month/all.",
                    "default": "all",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

TOOL_CALLING_TOOLS: list[dict] = [TOOL_EXECUTE_WEB_SEARCH, TOOL_QUERY_CHAT_MEMORY]
