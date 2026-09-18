"""Эпик 04.09.2026 (3.3, Часть 2) — JSON Schema инструментов Tool Calling.

Используются в цикле services/tool_loop.py для direct_chat (FR-17: только
direct_chat получает инструменты). Имена/состав/порядок тулов — канон R9
(не менять без ревизии spec: модели опираются на description при выборе
инструмента).

Раунд 9 (AGI Memory, T-820, spec §3.2.1/Q6): третий инструмент dig_into_lore
(ностальгия/старые события/годы). Порядок TOOL_CALLING_TOOLS = канону R9:
query_chat_memory → dig_into_lore → execute_web_search — при ностальгии
модель сначала копает память, а не веб (research §4(в)).

Раунд 10.15 (F8, ADR-1015-3 §3, T-1611): +4 инструмента
(summarize_video/download_media/get_bot_health/get_recent_history) — итого 7;
канон R9 сохранён, новые схемы добавлены в конец. Fast-Track regex (F6)
остаётся приоритетнее: инструменты ловят только свободную форму.

Раунд 10.17 (F2, T-1676, ADR-1017-2 §2.2 — SUPERSEDE ADR-1016-1 §2 п.3/§3):
`download_media` получает ОПЦИОНАЛЬНОЕ поле `quality` (enum = `QUALITY_ENUM`)
для ЯВНОГО запроса пользователя; без него бэкенд сам присылает меню качества
кнопками (как Fast-Track).

Раунд 10.20 (БЛОК 1/О3, ADR-1020-4, T-1887): 8-й инструмент «Летописец» —
`compile_lore_story(topic)` (EN-description) + гейт `active_tools()` по
флагу `flags.lore_compiler_enabled` (default ON).

Раунд 10.20 (БЛОК 7.4 — РЕВИЗИЯ КАНОНА 3.3, ADR-1020-7 §4, T-1925): **все**
`description` (схемы И параметры) переведены на **английский** + строгая
типизация (`additionalProperties: false` у всех; `enum`/`minimum`/`maximum`
на месте; у `summarize_video.mode` добавлено отсутствовавшее `description`).
Имена/состав/порядок/`required` НЕ меняются; `tool_choice` НЕ форсируется
(backlog §16 п.2). Прежние RU-описания — слепок `plans/docs/canon/architecture.md`
(тем же коммитом).
"""
from tools.video_downloader import QUALITY_ENUM

TOOL_EXECUTE_WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "execute_web_search",
        "description": "Search the web (cascade Tavily->Exa->DuckDuckGo). "
                       "Call when the answer needs fresh or external facts: "
                       "news, current events, verification of information "
                       "that is absent from the context and memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Search query (short, in any language)."}
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
        "description": "Search the bot's memory: this chat's history, who "
                       "wrote what and when, long-term facts, mention "
                       "statistics. Call FIRST when the question is about the "
                       "chat's past: 'how many times was a word or topic "
                       "mentioned', 'when did it happen', 'who talked about "
                       "...', 'what was written earlier'. The result contains "
                       "the match count and a date range - answer strictly "
                       "from it.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to recall."},
                "time_range": {
                    "type": "string",
                    "enum": ["last_day", "last_week", "last_month", "all"],
                    "description": "Time window: last_day/last_week/last_month/all.",
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
        # 10.20 (БЛОК 2.5, ADR-1020-2 п.4): роутинг-пара dig_into_lore ↔
        # compile_lore_story — EN-формулировка (дословно по ТЗ, стр. 55-56).
        # compile_lore_story регистрируется Фазой C (T-1887) с парной EN-строкой.
        "description": (
            "Use this for fast, factual lookups. Answers simple questions "
            "like 'Who owns X?', 'When did Y happen?'. Returns minimal, "
            "precise facts."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "What to dig up (required)."},
                "year": {"type": "integer",
                         "description": "Year of the event, e.g. 2024 "
                                        "(optional)."},
                "person": {"type": "string",
                           "description": "Participant name, e.g. Ivan "
                                          "(optional)."},
                "mode": {"type": "string",
                         "enum": ["messages", "facts", "both"],
                         "default": "both",
                         "description": "messages - chat log (FTS), facts - "
                                        "graph facts, both - both."},
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
        "description": ("Summary or transcript of a video by link "
                        "(YouTube/platforms/direct file). Call when the user "
                        "asks to retell/transcribe a clip and provides a link. "
                        "mode='transcript' - raw text; mode='summary' - "
                        "condensed summary."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Video link."},
                "mode": {"type": "string",
                         "enum": ["summary", "transcript"],
                         "default": "summary",
                         "description": "Output mode: 'summary' - condensed "
                                        "summary; 'transcript' - raw text."},
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
        "description": ("Download a video by link and send it as a file to "
                        "this chat. Call on a free-form request "
                        "'download/fetch/grab <link>'. Fill the quality field "
                        "ONLY if the user explicitly named a quality; "
                        "otherwise omit it - the backend will offer a quality "
                        "menu with buttons."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Video link."},
                "quality": {
                    "type": "string",
                    "enum": list(QUALITY_ENUM),
                    "description": ("Quality - ONLY on an explicit user "
                                    "request (e.g. 'download in 720p'); "
                                    "otherwise omit it - the backend will "
                                    "offer a buttons menu."),
                },
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
        "description": ("Show the bot's status/health (logs, memory, "
                        "services). Call on 'are you ok / how are you / check "
                        "health' when the command arrives in free form."),
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
        "description": ("Recent transcript of THIS chat: the latest messages "
                        "in order (Name: text). Call on 'what were we "
                        "discussing 10 minutes ago', 'who dropped that link', "
                        "'who is right in the argument', 're-read the last "
                        "messages'. depth - how many messages back (up to "
                        "150); OR query - search among the last hours' "
                        "messages. This is exact chronology, NOT semantic RAG."),
        "parameters": {
            "type": "object",
            "properties": {
                "depth": {"type": "integer", "minimum": 1, "maximum": 150,
                          "description": ("How many recent messages to return "
                                          "(default 50).")},
                "query": {"type": "string",
                          "description": ("Fragment/topic to search among "
                                          "recent messages (last hours).")},
            },
            "additionalProperties": False,
        },
    },
}

# Раунд 10.20 (БЛОК 1, ADR-1020-4, T-1887): 8-й инструмент «Летописец» —
# compile_lore_story(topic). Парная EN-формулировка к dig_into_lore
# (ADR-1020-2 п.4): тяжёлый нарратив против «быстрых точных фактов».
# Доступен только при `flags.lore_compiler_enabled` (default ON — О3):
# гейт `active_tools()` ниже, диспетчеру список отдаётся уже отфильтрованным.
TOOL_COMPILE_LORE_STORY = {
    "type": "function",
    "function": {
        "name": "compile_lore_story",
        # 10.20 (БЛОК 1/2.5, ТЗ стр. 56, ADR-1020-2 п.4): дословная EN-строка.
        "description": ("Use this ONLY when the user asks to explain a meme, "
                        "tell a story, or give a comprehensive historical "
                        "overview of a topic. Heavy narrative tool."),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string",
                          "description": "Local meme/topic/event to tell the "
                                         "story about."}
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
}

# Раунд 10.15 (F8, ADR-1015-3 §3): итоговый tool-сет — 7 инструментов.
# Раунд 10.20 (T-1887): +compile_lore_story → 8.
# Раунд 10.23 (F5, ADR-1023-5 §D2): +generate_image → 9 (в КОНЕЦ; порядок
# первых 8 — канон R9, байт-в-байт). Порядок сохраняет канон R9
# (память → лор → веб) и добавляет новые в конце. Имена/состав/порядок не
# меняются; `description` — EN (T-1925, ревизия канона 3.3).
TOOL_GENERATE_IMAGE = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": ("Generate an image from a text description and send "
                        "it to this chat. Call when the user asks to draw, "
                        "create, generate or imagine a picture, meme, art or "
                        "illustration."),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string",
                           "description": ("What to draw - a short visual "
                                           "description in any language.")}
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
}

TOOL_CALLING_TOOLS: list[dict] = [
    TOOL_QUERY_CHAT_MEMORY,
    TOOL_DIG_INTO_LORE,
    TOOL_EXECUTE_WEB_SEARCH,
    TOOL_SUMMARIZE_VIDEO,
    TOOL_DOWNLOAD_MEDIA,
    TOOL_GET_BOT_HEALTH,
    TOOL_GET_RECENT_HISTORY,
    TOOL_COMPILE_LORE_STORY,
    TOOL_GENERATE_IMAGE,
]

# Имя флагового инструмента (гейт flags.lore_compiler_enabled, О3).
LORE_COMPILER_TOOL_NAME = "compile_lore_story"
# Имя image-инструмента (гейт flags.image_generation_module_enabled, F5).
IMAGE_GENERATION_TOOL_NAME = "generate_image"


def active_tools(lore_compiler_enabled: bool = True,
                 image_generation_enabled: bool = False) -> list[dict]:
    """Tool-сет для LLM с учётом флагов «Летописец» (О3, T-1887) и
    генерации изображений (F5, ADR-1023-5 §D2).

    ``lore_compiler_enabled=False`` → compile_lore_story исключается.
    ``image_generation_enabled=False`` (дефолт) → generate_image исключён
    (список 8 имён байт-в-байт как до F5). Возвращается новый список —
    TOOL_CALLING_TOOLS (снапшот) не мутируется.
    """
    disabled: set[str] = set()
    if not lore_compiler_enabled:
        disabled.add(LORE_COMPILER_TOOL_NAME)
    if not image_generation_enabled:
        disabled.add(IMAGE_GENERATION_TOOL_NAME)
    if not disabled:
        return list(TOOL_CALLING_TOOLS)
    return [tool for tool in TOOL_CALLING_TOOLS
            if tool["function"]["name"] not in disabled]


# Раунд 10.20 (БЛОК 6.2, ADR-1020-5 п.1, T-1907): tool-сет ФАКТЧЕКА —
# ровно три инструмента вердиктного пайплайна (`dig_into_lore` +
# `compile_lore_story` + `execute_web_search`). Скачивание/выжимка в фактчеке
# не нужны (ADR §Альтернативы: «разрешить все 8» отклонено). Флаг «Летописца»
# (О3) действует и здесь: OFF → `compile_lore_story` исключён, два остальных
# работают. Реюз схем обычного диалога (байт-в-байт), без дублирования.
FACTCHECK_TOOL_NAMES: tuple[str, ...] = (
    "dig_into_lore", "compile_lore_story", "execute_web_search")

_FACTCHECK_TOOLS: tuple[dict, ...] = (
    TOOL_DIG_INTO_LORE, TOOL_COMPILE_LORE_STORY, TOOL_EXECUTE_WEB_SEARCH)


def factcheck_tools(lore_compiler_enabled: bool = True) -> list[dict]:
    """Tool-сет фактчекера (T-1907, ADR-1020-5 п.1).

    Возвращает новый список — снапшот `_FACTCHECK_TOOLS` не мутируется.
    ``False`` → `compile_lore_story` исключён (7→8-инструментный гейт О3
    распространяется и на фактчекер).
    """
    if lore_compiler_enabled:
        return list(_FACTCHECK_TOOLS)
    return [tool for tool in _FACTCHECK_TOOLS
            if tool["function"]["name"] != LORE_COMPILER_TOOL_NAME]
