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

Раунд 10.24 (F14, ADR-1024-15 §2.1/§2.3 — AMEND ADR-1015-3/ADR-1020-4, UPD5):
контракт нативного источника — `summarize_video`/`download_media` получают
ОПЦИОНАЛЬНЫЙ `url` + `source: enum["link","reply"]`; у `summarize_video`
удалён `mode` (инструмент = только выжимка). Контракт второго инструмента —
`transcribe_video` (сырая транскрибация) — определён здесь (`TOOL_TRANSCRIBE_VIDEO`).

Раунд 10.24 (F19, ADR-1024-20 §2.1/§2.2 — AMEND ADR-1020-4, ступень F14 → F19):
`transcribe_video` **зарегистрирован** в `TOOL_CALLING_TOOLS` 10-м (в конец,
канон-дисциплина «новое — в хвост»; первые 9 — байт-в-байт). Канон R9 = **10**;
техдолг 10.23 I2 (комментарий-счётчик) закрыт. LLM-доступность
`transcribe_video` гейтится env-only `MEDIA_TRANSCRIBE_TOOL_ENABLED`
(`active_tools`); само наличие схемы/счётчик — безусловны.

Раунд 10.26 (A2, ADR-1026-15 D5 — санкция ADR-1026-13 D3): канон R9 = **11**;
11-й — `fetch_article` (`TOOL_FETCH_ARTICLE`, в конец, первые 10 — байт-в-байт),
URL→Markdown+метаданные. LLM-доступность гейтится env-only
`ARTICLE_TOOL_ENABLED` (`active_tools`); схема/канон безусловны (Δ каталога=0).

Раунд 10.26 (A6, ADR-1026-18 D1 — новая санкция, ADR-1026-13 D3 исчерпана A2):
канон R9 = **12**; 12-й — `get_user_context` (`TOOL_GET_USER_CONTEXT`, в конец,
первые 11 — байт-в-байт), structured memory lookup поверх существующего
досье/RAG (§32–§35). LLM-доступность гейтится env-only
`MEMORY_LOOKUP_ENABLED` (`active_tools`); схема/канон безусловны (Δ каталога=0).
"""
from config.settings import settings
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
        "description": (
            "Make a SUMMARY (a condensed retelling) of a video: what it is "
            "about and its key points. Call when the user wants an overview of "
            "a video: 'what is this video about', 'what's in the video', "
            "'retell/summarize this clip'. Source is a link (YouTube/platforms/"
            "direct file) OR the video from the replied message. Returns a "
            "SUMMARY, not the raw transcript."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": ("Video link (YouTube/platforms/direct "
                                        "file). Omit when the video comes from "
                                        "the replied message.")},
                "source": {"type": "string",
                           "enum": ["link", "reply"],
                           "description": ("Where to take the video from: "
                                           "'link' - use url; 'reply' - use the "
                                           "video/document from the replied "
                                           "message.")},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}

# Раунд 10.24 (F14, ADR-1024-15 §2.3-bis, UPD5): контракт второго
# медиа-инструмента — сырая транскрибация (дословный текст, без пересказа).
# F14 фиксирует EN-определение; регистрацию (10-й, в конец) и dispatch ведёт
# F19 (T-2344/T-2345/T-2349) поверх этой схемы — без дублирования правки.
TOOL_TRANSCRIBE_VIDEO = {
    "type": "function",
    "function": {
        "name": "transcribe_video",
        "description": (
            "Transcribe a video or voice note into RAW verbatim text (an "
            "audio transcript), without retelling. Call when the user "
            "explicitly asks for a 'transcript'/'transcription' or to repeat/"
            "re-transcribe a voice message, video note or video. Source is a "
            "link (YouTube/platforms/direct) OR the media from the replied "
            "message. Return the raw transcript VERBATIM - do NOT summarize, "
            "shorten or retell it."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": ("Video link (YouTube/platforms/direct "
                                        "file). Omit when the media comes from "
                                        "the replied message.")},
                "source": {"type": "string",
                           "enum": ["link", "reply"],
                           "description": ("Where to take the media from: "
                                           "'link' - use url; 'reply' - use the "
                                           "video/voice from the replied "
                                           "message.")},
            },
            "required": [],
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
                        "'download/fetch/grab <link>'. Source is a link OR the "
                        "video from the replied message. Fill the quality field "
                        "ONLY if the user explicitly named a quality; "
                        "otherwise omit it - the backend will offer a quality "
                        "menu with buttons."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": ("Video link. Omit when the video comes "
                                        "from the replied message.")},
                "source": {"type": "string",
                           "enum": ["link", "reply"],
                           "description": ("Where to take the video from: "
                                           "'link' - use url; 'reply' - use the "
                                           "video/document from the replied "
                                           "message.")},
                "quality": {
                    "type": "string",
                    "enum": list(QUALITY_ENUM),
                    "description": ("Quality - ONLY on an explicit user "
                                    "request (e.g. 'download in 720p'); "
                                    "otherwise omit it - the backend will "
                                    "offer a buttons menu."),
                },
            },
            "required": [],
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
# Раунд 10.23 (F5, ADR-1023-5 §D2): +generate_image → 9 (в КОНЕЦ).
# Раунд 10.24 (F19, ADR-1024-20 §2.1, UPD5): канон R9 → **10**; 10-й —
# transcribe_video (в КОНЕЦ, контракт `TOOL_TRANSCRIBE_VIDEO` выше; ступень
# F14 → F19). Порядок первых 9 имён — байт-в-байт.
# Раунд 10.26 (A2, ADR-1026-15 D5): канон → **11**; 11-й — `fetch_article`
# (в КОНЕЦ, контракт `TOOL_FETCH_ARTICLE` ниже; санкция ADR-1026-13 D3).
# Порядок первых 10 имён — байт-в-байт. Комментарий-счётчик соответствует
# фактическому набору (**11**).
# Имена/состав/порядок сохраняют канон R9 (память → лор → веб) и добавляют
# новые в конце; `description` — EN (T-1925, ревизия канона 3.3).
# A3 (ADR-1026-16 D4, санкция — ТОЛЬКО текст описания; состав/имена/порядок/
# required/additionalProperties не меняются; канон = 11): описание приведено
# к 6 пунктам §21 (когда вызывать / обязательные аргументы / как формировать
# описание / что при отсутствии контекста / как интерпретировать результат /
# как сообщать об ошибке). OFF-киль-свитч `UNIFIED_IMAGE_REQUEST_ENABLED`
# возвращает прежний текст (D6: OFF → legacy).
TOOL_GENERATE_IMAGE_LEGACY = {
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

TOOL_GENERATE_IMAGE_V21 = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Generate an image from a text description and send it to this "
            "chat. WHEN TO CALL: the user asks (in free form) to draw, "
            "create, generate or imagine a picture, meme, art or "
            "illustration. Do NOT call it for a direct \"Bot/bot, draw ...\" "
            "command - the backend already handles that automatically. "
            "REQUIRED ARGUMENT: prompt (string, mandatory). HOW TO BUILD THE "
            "PROMPT: describe what to draw as a rich visual description "
            "(subject, composition, style, colors); follow the meaning of "
            "the user's request and do not add content they did not ask for. "
            "WITHOUT EXTRA CONTEXT: plain understanding of the user's "
            "description is enough - do not search memory or documents for "
            "every request. HOW TO INTERPRET THE RESULT: the tool returns "
            "JSON; the backend delivers the image (or a friendly failure "
            "message) to the chat itself - do not describe or repeat the "
            "image afterward. ON ERROR: the JSON contains the actual failure "
            "reason; tell the user briefly that generating the image failed "
            "just now and suggest trying later - do not invent a different "
            "reason and do not claim the model refused."),
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

# A3 (D4/D6): активный текст описания выбирается env-киль-свитчем
# `UNIFIED_IMAGE_REQUEST_ENABLED` (default ON → уточнённое описание;
# OFF → байт-в-байт прежний текст legacy-пути). Структура (name/тип/схема/
# required) идентична в обоих вариантах — канон не меняется.
TOOL_GENERATE_IMAGE = (
    TOOL_GENERATE_IMAGE_V21
    if getattr(settings, "UNIFIED_IMAGE_REQUEST_ENABLED", True)
    else TOOL_GENERATE_IMAGE_LEGACY
)

# Раунд 10.26 (A2, ADR-1026-15 D5): 11-й инструмент — `fetch_article`
# (URL → Markdown+метаданные). Атомарное расширение канона 10 → 11:
# схема + регистрация (в КОНЕЦ, «новое — в хвост», ADR-1020-4) + метод
# роутера + `active_tools` + тесты. Фактчек-инструмент/§36–§37 — граница A7.
TOOL_FETCH_ARTICLE = {
    "type": "function",
    "function": {
        "name": "fetch_article",
        "description": (
            "Fetch a web ARTICLE by link and return its text as Markdown with "
            "metadata. Call when the user shares a link (or replies to a "
            "message with a link) and wants its content, a summary, or facts "
            "from it. Source is the url field OR a link already available in "
            "the context (omit url then). Returns Markdown text, not a raw "
            "HTML page."),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": ("Article link (http/https). Omit when "
                                        "the link is already available in the "
                                        "context (current message/reply).")},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}

# Раунд 10.26 (A6, ADR-1026-18 D1/D2): 12-й инструмент — `get_user_context`
# (structured memory lookup поверх существующего досье/RAG; §32–§35).
# Атомарное расширение канона 11 → 12: схема + регистрация (в КОНЕЦ, «новое —
# в хвост», ADR-1020-4) + метод роутера + `active_tools` + тесты `len==12`.
# Память ≠ фактчек (§35): набор `factcheck_tools` остаётся 3 и не расширяется.
TOOL_GET_USER_CONTEXT = {
    "type": "function",
    "function": {
        "name": "get_user_context",
        "description": (
            "Look up what is KNOWN ABOUT one specific person (dossier + "
            "long-term memory). Call on your own initiative when the answer "
            "needs facts about a person: 'what do you know about X', 'who is "
            "X', 'describe X', 'how does X usually talk', 'who is X related "
            "to', 'what did X say'. Required: person (name/@username/numeric "
            "id as a string) and purpose. purpose=identity (who this is), "
            "appearance (looks), speech_style (how this person talks), "
            "biography (life facts), relationships (connections), general "
            "(relevant messages/facts). Pass user_id when you already know it "
            "- it takes priority over person. This tool returns MEMORY only: "
            "it confirms what was SAID, never whether it is TRUE - it is NOT "
            "fact-checking; to verify the CONTENT of a claim use the "
            "fact-check tools. Missing data is reported honestly (no_data) - "
            "never present unconfirmed information as an established fact."),
        "parameters": {
            "type": "object",
            "properties": {
                "person": {
                    "type": "string",
                    "description": ("Name, @username or numeric id of the "
                                    "person (as a string).")},
                "user_id": {
                    "type": "integer",
                    "description": ("Optional numeric Telegram user id; takes "
                                    "priority over person when provided.")},
                "purpose": {
                    "type": "string",
                    "enum": ["identity", "appearance", "speech_style",
                             "biography", "relationships", "general"],
                    "description": ("What to look up: identity - who this is; "
                                    "appearance - looks; speech_style - how "
                                    "they talk; biography - life facts; "
                                    "relationships - connections; general - "
                                    "relevant messages/facts.")},
                "max_items": {
                    "type": "integer",
                    "minimum": 1,
                    "description": ("Optional cap on returned items "
                                    "(default per purpose; hard ceiling 20).")},
            },
            "required": ["person", "purpose"],
            "additionalProperties": False,
        },
    },
}

# Канон R9 = **12** (A6, ADR-1026-18 D1): первые 11 — байт-в-байт,
# get_user_context — в конец.
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
    TOOL_TRANSCRIBE_VIDEO,
    TOOL_FETCH_ARTICLE,
    TOOL_GET_USER_CONTEXT,
]

# Имя флагового инструмента (гейт flags.lore_compiler_enabled, О3).
LORE_COMPILER_TOOL_NAME = "compile_lore_story"
# Имя image-инструмента (гейт flags.image_generation_module_enabled, F5).
IMAGE_GENERATION_TOOL_NAME = "generate_image"
# F14: имя контракта сырой транскрибации (регистрацию/гейт ведёт F19).
TRANSCRIBE_TOOL_NAME = "transcribe_video"
# A2 (ADR-1026-15 D5): имя инструмента извлечения статьи (env-only гейт).
ARTICLE_TOOL_NAME = "fetch_article"
# A6 (ADR-1026-18 D1): имя инструмента structured memory lookup (env-only гейт).
MEMORY_LOOKUP_TOOL_NAME = "get_user_context"


def _transcribe_tool_enabled() -> bool:
    """env-only kill-switch ``MEDIA_TRANSCRIBE_TOOL_ENABLED`` (F19, default ON).

    Гейтит только LLM-доступность ``transcribe_video`` (ADR-1024-20 §2.4):
    OFF → инструмент не объявляется (прежний набор без него). Наличие схемы
    и канон ``TOOL_CALLING_TOOLS == 10`` — безусловны."""
    return bool(getattr(settings, "MEDIA_TRANSCRIBE_TOOL_ENABLED", True))


def _article_tool_enabled() -> bool:
    """env-only kill-switch ``ARTICLE_TOOL_ENABLED`` (A2, ADR-1026-15 D5; ON).

    Гейтит только LLM-доступность ``fetch_article``: OFF → инструмент не
    объявляется (эффективный канон 10). Наличие схемы ``TOOL_FETCH_ARTICLE``
    и канон ``TOOL_CALLING_TOOLS == 11`` — безусловны (Δ каталога = 0)."""
    return bool(getattr(settings, "ARTICLE_TOOL_ENABLED", True))


def _memory_lookup_enabled() -> bool:
    """env-only kill-switch ``MEMORY_LOOKUP_ENABLED`` (A6, ADR-1026-18 D1; ON).

    Гейтит только LLM-доступность ``get_user_context``: OFF → инструмент не
    объявляется (эффективный канон без него), остальные имена — байт-в-байт.
    Наличие схемы ``TOOL_GET_USER_CONTEXT`` и канон ``TOOL_CALLING_TOOLS == 12``
    — безусловны (Δ каталога = 0)."""
    return bool(getattr(settings, "MEMORY_LOOKUP_ENABLED", True))


def active_tools(lore_compiler_enabled: bool = True,
                 image_generation_enabled: bool = False) -> list[dict]:
    """Tool-сет для LLM с учётом флагов «Летописец» (О3, T-1887),
    генерации изображений (F5, ADR-1023-5 §D2), транскрибации (F19,
    ADR-1024-20 §2.4), извлечения статьи (A2, ADR-1026-15 D5) и memory
    lookup (A6, ADR-1026-18 D1).

    ``lore_compiler_enabled=False`` → compile_lore_story исключается.
    ``image_generation_enabled=False`` (дефолт) → generate_image исключён
    (список из 11 имён, как после A2).
    ``MEDIA_TRANSCRIBE_TOOL_ENABLED`` OFF (env) → transcribe_video исключён.
    ``ARTICLE_TOOL_ENABLED`` OFF (env) → fetch_article исключён.
    ``MEMORY_LOOKUP_ENABLED`` OFF (env) → get_user_context исключён
    (первые 11 имён — байт-в-байт).
    Возвращается новый список — TOOL_CALLING_TOOLS (снапшот) не мутируется.
    """
    disabled: set[str] = set()
    if not lore_compiler_enabled:
        disabled.add(LORE_COMPILER_TOOL_NAME)
    if not image_generation_enabled:
        disabled.add(IMAGE_GENERATION_TOOL_NAME)
    if not _transcribe_tool_enabled():
        disabled.add(TRANSCRIBE_TOOL_NAME)
    if not _article_tool_enabled():
        disabled.add(ARTICLE_TOOL_NAME)
    if not _memory_lookup_enabled():
        disabled.add(MEMORY_LOOKUP_TOOL_NAME)
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
