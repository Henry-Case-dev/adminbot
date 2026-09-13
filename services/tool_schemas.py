"""Эпик 04.09.2026 (3.3, Часть 2) — JSON Schema инструментов Tool Calling.

Используются в цикле services/tool_loop.py для direct_chat (FR-17: только
direct_chat получает инструменты). Имена/схемы — канон 3.3 (не менять без
ревизии spec: модели опираются на description при выборе инструмента).

Раунд 9 (AGI Memory, T-820, spec §3.2.1/Q6): третий инструмент dig_into_lore
(ностальгия/старые события/годы). Порядок TOOL_CALLING_TOOLS = канону R9:
query_chat_memory → dig_into_lore → execute_web_search — при ностальгии
модель сначала копает память, а не веб (research §4(в)).

Раунд 10.15 (F8, ADR-1015-3 §3, T-1611): +4 инструмента
(summarize_video/download_media/get_bot_health/get_recent_history) — итого 7;
канон R9 сохранён, новые схемы добавлены в конец. Fast-Track regex (F6)
остаётся приоритетнее: инструменты ловят только свободную форму.
"""

TOOL_EXECUTE_WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "execute_web_search",
        "description": "Поиск в интернете (каскад Tavily→Exa→DuckDuckGo). "
                       "Вызывай, когда ответу нужны свежие или внешние факты: новости, "
                       "актуальные события, проверка информации, которой нет в контексте и в памяти.",
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
        "description": "Поиск по памяти бота: история этого чата, кто и когда писал, "
                       "долгосрочные факты, статистика упоминаний. Вызывай ПЕРВЫМ, когда вопрос "
                       "про прошлое чата: «сколько раз упоминалось слово или тема», «когда это "
                       "было», «кто говорил про …», «что писали раньше». Результат содержит число "
                       "совпадений и диапазон дат — отвечай точно по нему.",
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

TOOL_DIG_INTO_LORE = {
    "type": "function",
    "function": {
        "name": "dig_into_lore",
        "description": ("Глубокое копание в историю чата с датами и именами: "
                        "помнишь/а помните/как мы тогда/в 2024/что было с "
                        "{имя}/ровно год назад/кто был тот. Вызывай ПЕРВЫМ и "
                        "ОБЯЗАТЕЛЬНО до ответа, когда речь про старое событие, "
                        "конкретный год или человека из прошлого чата. В query "
                        "передай тему, в year - год (если назван), в person - имя "
                        "(если названо). Результат: датированные выдержки из "
                        "переписки и факты."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "О чем вспомнить (обязательно)."},
                "year": {"type": "integer",
                         "description": "Год события, например 2024 "
                                        "(необязательно)."},
                "person": {"type": "string",
                           "description": "Имя участника, например Ваня "
                                          "(необязательно)."},
                "mode": {"type": "string",
                         "enum": ["messages", "facts", "both"],
                         "default": "both",
                         "description": "messages - переписка (FTS), facts - "
                                        "факты графа, both - и то и то."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

TOOL_SUMMARIZE_VIDEO = {
    "type": "function",
    "function": {
        "name": "summarize_video",
        "description": ("Выжимка или расшифровка видео по ссылке (YouTube/платформы/прямой файл). "
                        "Вызывай, когда пользователь просит пересказать/расшифровать ролик и дал ссылку. "
                        "mode='transcript' — сырой текст; mode='summary' — сжатая выжимка."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Ссылка на видео."},
                "mode": {"type": "string",
                         "enum": ["summary", "transcript"],
                         "default": "summary"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}

TOOL_DOWNLOAD_MEDIA = {
    "type": "function",
    "function": {
        "name": "download_media",
        "description": ("Скачать видео по ссылке и отправить файлом в этот чат. "
                        "Вызывай на просьбу «скачай/загрузи/стяни <ссылка>» в свободной форме."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Ссылка на видео."},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}

TOOL_GET_BOT_HEALTH = {
    "type": "function",
    "function": {
        "name": "get_bot_health",
        "description": ("Показать статус/здоровье бота (логи, память, сервисы). "
                        "Вызывай на вопрос «ты в порядке / как дела / чекни здоровье», "
                        "если команда пришла свободной формой."),
        "parameters": {"type": "object", "properties": {},
                       "additionalProperties": False},
    },
}

# F9 (`recent-history-tool-round1015`): кратковременная память — сырая
# хронологическая стенограмма недавних сообщений (НЕ векторный RAG). F8
# регистрирует схему и dispatch-ветку; полная логика — в F9.
TOOL_GET_RECENT_HISTORY = {
    "type": "function",
    "function": {
        "name": "get_recent_history",
        "description": ("Недавняя стенограмма ЭТОГО чата: последние сообщения по порядку (Имя: текст). "
                        "Вызывай на «что обсуждали 10 минут назад», «кто скинул ту ссылку», "
                        "«кто прав в споре», «перечитай последние сообщения». "
                        "depth — сколько сообщений вглубь (до 150); ЛИБО query — поиск по недавним "
                        "сообщениям последних часов. Это точная хронология, НЕ смысловой RAG."),
        "parameters": {
            "type": "object",
            "properties": {
                "depth": {"type": "integer", "minimum": 1, "maximum": 150,
                          "description": "Сколько последних сообщений вернуть (по умолчанию 50)."},
                "query": {"type": "string",
                          "description": ("Фрагмент/тема для поиска по недавним сообщениям "
                                          "(последние часы).")},
            },
            "additionalProperties": False,
        },
    },
}

# Раунд 10.15 (F8, ADR-1015-3 §3): итоговый tool-сет — 7 инструментов.
# Порядок сохраняет канон R9 (память → лор → веб) и добавляет новые в конце.
# Существующие имена/схемы не меняются (модель опирается на description).
TOOL_CALLING_TOOLS: list[dict] = [
    TOOL_QUERY_CHAT_MEMORY,
    TOOL_DIG_INTO_LORE,
    TOOL_EXECUTE_WEB_SEARCH,
    TOOL_SUMMARIZE_VIDEO,
    TOOL_DOWNLOAD_MEDIA,
    TOOL_GET_BOT_HEALTH,
    TOOL_GET_RECENT_HISTORY,
]
