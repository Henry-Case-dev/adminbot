"""Эпик 04.09.2026 (3.3, Часть 2) — исполнение инструментов Tool Calling.

Фиксированный реестр имён (dispatch по таблице, БЕЗ исполнения произвольного
кода); аргументы валидируются (кривой JSON/тип → текст ошибки); результаты
режутся (4000/3500 симв.); параллельного исполнения НЕТ (последовательно, по
одному tool_call за раунд — бюджет в tool_loop).

dispatch ВСЕГДА возвращает строку результата (в т.ч. 'ОШИБКА …') — НЕ бросает
(FR-14: результат ошибки уходит модели как role:"tool").

Раунд 9 (AGI Memory, T-820, spec §3.2.1/Q6): ветка _dig_into_lore — глубокое
копание в историю чата (датированные сниппеты L1 по FTS5 + факты графа);
флаг flags.dig_enabled (default true; hot-фолбек settings.DIG_ENABLED); год →
диапазон по timestamp (в т.ч. «N лет назад» из query); person → user_id-
фильтр (если алиас) + OR-токены имён + расширение именами из граф-обхода
(nodes/edges, глубина limits.dig_graph_hop_depth; фолбэк target_user);
лимиты — hot-ключи группы limits_memory с фолбэком settings (REGISTRY
фикс-раунда, spec §3.6.4). НЕ бросает: ошибка этапа → WARNING + секция пуста.

Раунд 10.15 (F8, ADR-1015-3, T-1612…T-1615): +4 инструмента tool-сета —
summarize_video (делегирование YoutubeSummarizerService), download_media
(корнер-кейс: бэкенд сам шлёт MP4, в LLM — фиктивный tool_response),
get_bot_health (CheckupLogsFetcher+CheckupService) и get_recent_history
(полная реализация — F9, см. ниже). ToolDeps/ToolContext расширены аддитивно
(обратная совместимость: старые вызовы без новых kwargs работают).

Раунд 10.15 (F9, spec §2-§6, T-1620…T-1623): `_get_recent_history` реализован
полностью — сырая хронологическая стенограмма недавних сообщений чата
(«Имя: текст»): путь `depth` (≤150) через `database.get_recent_messages` либо
путь `query` (FTS + окно последних часов + ASC). Лимиты — код-константы
(каталог-Δ=0); R17: логи только chat_id/count/out_chars.

Раунд 10.17 (F2, ADR-1017-2 — SUPERSEDE ADR-1016-1 §2 п.3/§3): tool
`download_media` для платформенного URL делает `probe()` → инлайн-меню
качества `tdq:<height>` → фиктивный `tool_response {"status":"needs_quality"}`
(скачивание доводит callback `tdq:` в роутере 4e); прямой медиа-URL или явно
названное `quality` — сразу `download(url, quality)`; провал probe — одна
bounded попытка `download(url, None)`. Кулдаун (D279) — только после успеха.

Раунд 10.20 (БЛОК 1/О3, ADR-1020-4 п.1-4, T-1887): 8-й тул
`compile_lore_story(topic)` — «Летописец». Dispatch делегирует в
изолированный `LoreCompilerService` (Шаг А граф + Шаг Б хронология → свой
канон `LORE_STORY_SYSTEM_PROMPT` → готовый рассказ), ставит
`ToolContext.lore_compiled = True` (сигнал доставки HTML — ADR-1020-6);
гейт `flags.lore_compiler_enabled` (default ON). Ошибки → «ОШИБКА …».

Раунд 10.24 (F19, ADR-1024-20 §2.2): `transcribe_video` — СЫРАЯ
транскрибация (дословный текст, без пересказа), отдельно от `summarize_video`.
Источник link/native (voice/video_note включительно); YouTube → субтитры raw,
иначе download→STT; native → fetch→STT. Возвращает строку (усечённую
`_MEMORY_MAX_SYMBOLS`), никогда не бросает. Egress не расширяется.
"""
import asyncio
import datetime
import hashlib
import json
import logging
import re
import time

from config.settings import settings
from services import hot_config as hot
from services import image_context_memory
from services import image_generation
from services import media_share
from services import native_media
from services.canonical_context import format_context_item, resolve_item_id
from services.media_send import send_media, send_quality_menu
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
)
from services.search_aggregator import AllSearchEnginesFailedException
from services.smartmodule_urls import extract_urls, extract_youtube_video_id
from services.tool_schemas import _memory_lookup_enabled
from services.web_content_extractor import WebContentExtractionFailedException
from tools.video_downloader import DownloadError, is_direct_media_url

logger = logging.getLogger(__name__)

# Лимиты результатов инструментов (3.3): символы.
_SEARCH_MAX_SYMBOLS = 4000
_MEMORY_MAX_SYMBOLS = 3500
_MEMORY_FTS_LIMIT = 40
_MEMORY_VEC_LIMIT = 15
# Бюджет одного инструмента веб-поиска (сумма таймаутов каскада + запас).
_SEARCH_TOOL_TIMEOUT = 25.0

# Раунд 10.15 (F8, ADR-1015-3 §8): таймауты новых инструментов — код-константы
# (новых каталог-ключей нет). download_media — в пределах NFR-4 скачивания;
# summarize_video — страховка поверх внутреннего бюджета сервиса.
_DOWNLOAD_TOOL_TIMEOUT = 180.0
_SUMMARIZE_TOOL_TIMEOUT = 300.0
# Раунд 10.20 (БЛОК 1, ADR-1020-4 п.3, T-1887): «Летописец» делает ВТОРОЙ
# LLM-вызов (синтез) — страховочный wait_for поверх него (как summarize_video).
_LORE_TOOL_TIMEOUT = 300.0
# Служебная инструкция tool-response: детерминизм доставки — в ctx
# (`lore_compiled`), но модель просим вернуть story дословно (мягкая страховка).
_LORE_RETURN_INSTRUCTION = (
    "[СИСТЕМНАЯ ИНСТРУКЦИЯ: верни пользователю текст из поля \"story\" "
    "ДОСЛОВНО, без сокращений, без пересказа и без собственных добавлений.]")
# Cap транскрипта для mode=transcript (прецедент handlers/youtube T-690).
_SUMMARIZE_TRANSCRIPT_CAP = 20000

# Раунд 10.24 (F14, ADR-1024-15 §2.3/§2.5): нативный источник инструментов
# (summarize_video/download_media) — только video/видео-document; bytes берём
# из разрешённого aiogram-объекта `ToolContext.native_media` (не из текста
# модели). STT-таймаут — паритет с youtube (`limits.video_stt_timeout_seconds`);
# download-кулдаун на нативную пересылку НЕ жжётся (копирование TG-файла,
# паритет Fast-Track). Kill-switch `NATIVE_MEDIA_TOOLS_ENABLED` гейтит нативный
# резолв (OFF → прежние ошибки, native fetch/STT не запускаются).
# F19 (ADR-1024-20 §2.5): наборы kind-ов — единый источник `services.native_media`
# (`VIDEO_KINDS` для summarize/download; `MEDIA_KINDS` — включая voice/video_note
# для `transcribe_video`), без дублирующих локальных констант.
_DOWNLOAD_NATIVE_MAX_BYTES = 2_000_000_000

# Раунд 10.26 (A2, ADR-1026-15 D5): инструмент `fetch_article` — извлечение
# статьи по URL в Markdown+метаданные через reuse `WebContentExtractor.extract`
# (каскад trafilatura 10 c / Tavily 15 c / Exa 15 c + запас). Код-константы
# (Δ каталога = 0).
_ARTICLE_TOOL_TIMEOUT = 45.0
_ARTICLE_MAX_SYMBOLS = 8000        # markdown-статья богаче поиска; всё ещё bounded

# ── A6 (раунд 10.26, ADR-1026-18 D3/D4/D5): structured memory lookup
# `get_user_context`. Капы — код-константы (Δ каталога = 0); инструмент
# read-only и free/local (не в METERED_TOOLS). R17: в логи — только
# purpose/user_id/chat_id/count/latency/empty_reason.
_MEMORY_LOOKUP_MAX_ITEMS_HARD = 20          # hard-ceiling max_items (D5)
_MEMORY_LOOKUP_MESSAGE_SLICE_MAX = 5        # срез сообщений (hard 10)
_MEMORY_LOOKUP_MESSAGE_SLICE_HARD = 10
_MEMORY_LOOKUP_SLICE_MAX_CHARS = 240        # символов на фрагмент сообщения
_MEMORY_LOOKUP_RESULT_MAX_CHARS = 4000      # общий бюджет результата
_MEMORY_LOOKUP_CONFIRMED_WEIGHT = 0.5       # graph_facts.weight → confirmed/likely
_MEMORY_LOOKUP_APPEARANCE_SCAN = 200        # bounded-пул под лексиконный фильтр
_MEMORY_LOOKUP_STYLE_SCAN = 120             # bounded-пул recent-сообщений
_MEMORY_LOOKUP_STYLE_MIN_MESSAGES = 2       # ниже минимума — включаем RAG (D3)
_MEMORY_LOOKUP_PORTRAIT_MAX_CHARS = 600     # портрет/профиль (производные)
_MEMORY_LOOKUP_RAG_FACT_CHARS = 240         # фрагмент RAG-факта
# Per-purpose дефолты max_items (D5, spec §3.5).
_MEMORY_LOOKUP_PURPOSE_DEFAULTS = {
    "identity": 5,
    "appearance": 10,
    "speech_style": 5,
    "biography": 10,
    "relationships": 10,
    "general": 8,
}
_MEMORY_LOOKUP_PURPOSES = tuple(_MEMORY_LOOKUP_PURPOSE_DEFAULTS)
# Лексикон внешности — generic-фильтр поверх graph_facts (A6). Извлечение/
# классификация внешности (в т.ч. из изображений) — граница A4 (U1).
_APPEARANCE_LEXICON = (
    "внешн", "выгляд", "причёс", "причес", "волос", "бород", "усы", "очк",
    "одет", "одежд", "носит", "высок", "низк", "худ", "полн", "толст",
    "стройн", "глаз", "улыб", "тату", "шрам", "рост", "лицо", "шляп", "кепк",
    "куртк", "костюм", "кроссовк", "пальто", "стриж", "бров", "родинк",
    "веснушк", "седин", "лыс", "модн",
)

# Раунд 10.17 (F2, ADR-1017-2 §2.1/§2.6): tool-скачивание спрашивает качество
# (probe → инлайн-меню `tdq:<height>` → callback доводит download). Таймаут
# probe в tool-пути — с запасом над внутренним `_PROBE_TIMEOUT_SECONDS=20`;
# pending-состояние — in-memory с TTL (как Fast-Track `_PENDING`). Код-константы
# (каталог-Δ=0).
_PROBE_TOOL_TIMEOUT = 25.0
_TOOL_DL_PENDING_TTL_SECONDS = 600
_TOOL_QUALITY_PREFIX = "tdq:"             # callback меню качества tool-пути

# Раунд 10.15 (F9, spec §6): лимиты get_recent_history — код-константы
# (каталог-Δ=0; прецедент _DIG_GRAPH_MAX_HOP_DEPTH/_MEMORY_FTS_LIMIT).
_HISTORY_MAX_DEPTH = 150                 # верхняя граница depth (UPD §5)
_HISTORY_DEFAULT_DEPTH = 50              # default при отсутствии параметров
_HISTORY_SEARCH_LIMIT = 80               # FTS-строк на этапе query (до фильтра)
_HISTORY_QUERY_WINDOW_SECONDS = 12 * 3600  # «последние часы» для query
_HISTORY_MAX_SYMBOLS = 3500              # обрезка результата (как _MEMORY_MAX_SYMBOLS)
_HISTORY_TOOL_TIMEOUT = 10.0             # страховочный wait_for (локальная SQLite)
# Честная фраза при пустом результате: модель не выдумывает (spec §3).
_HISTORY_EMPTY = "За последние сообщения ничего не нашлось"

# Окна query_chat_memory (3.3): time_range → секунды (0 = всё время).
_TIME_RANGE_SECONDS = {
    "last_day": 24 * 3600,
    "last_week": 7 * 24 * 3600,
    "last_month": 30 * 24 * 3600,
    "all": 0,
}

# Bugfix 04.09.2026 (Часть 2, 3.3(г)): человечные лейблы окна для заголовка
# счётчика query_chat_memory.
_TIME_RANGE_LABELS = {
    "last_day": "за сутки",
    "last_week": "за неделю",
    "last_month": "за месяц",
    "all": "за всё время",
}

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)

# Валидация ссылок инструментов (F8): только http(s)-URL.
_HTTP_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def _is_http_url(url: str) -> bool:
    """True — строка похожа на http(s)-ссылку (иначе инструмент → ОШИБКА)."""
    return bool(_HTTP_URL_RE.match(str(url or "").strip()))


def _path_ext(path) -> str:
    """Расширение tmp-файла для STT (без точки); пусто/нет суффикса → ``mp4``."""
    try:
        suffix = str(getattr(path, "suffix", "") or "").lstrip(".")
    except Exception:
        suffix = ""
    return suffix or "mp4"


def _native_tools_enabled() -> bool:
    """env-only kill-switch ``NATIVE_MEDIA_TOOLS_ENABLED`` (default ON).

    Единая точка чтения флага для нативного резолва инструментов
    (F14 §9/ADR-1024-15 §2.5). OFF → нативные вызовы без ``url`` не
    исполняются (прежние строки ошибок, native fetch/STT не запускаются)."""
    return bool(getattr(settings, "NATIVE_MEDIA_TOOLS_ENABLED", True))


def _download_status(status: str, message: str) -> str:
    """Фиктивный tool_response для download_media (ADR-1015-3 §4): LLM видит
    JSON, а реальный MP4 уходит в чат на бэкенде (модель не «печатает» файл).
    Статусы: success | needs_quality (меню отправлено) | error (ADR-1017-2 §3.2)."""
    return json.dumps({"status": status, "message": message},
                      ensure_ascii=False)


# Раунд 10.17 (F2, ADR-1017-2 §2.6): pending выбора качества tool-скачивания.
# Key `(chat_id, user_id)`; TTL `_TOOL_DL_PENDING_TTL_SECONDS`; ленивая чистка
# при каждом обращении. In-memory (без PG/DDL) — по ADR.
_TOOL_DL_PENDING: dict[tuple[int, int], dict] = {}


def _purge_stale_pending(now: float) -> None:
    """Ленивая чистка протухших записей pending (без отдельного таймера)."""
    for key in [k for k, v in _TOOL_DL_PENDING.items()
                if v.get("expires", 0) <= now]:
        _TOOL_DL_PENDING.pop(key, None)


def store_tool_download_pending(chat_id: int, user_id, *, url: str,
                                title, qualities, trigger_message_id) -> None:
    """Сохранить выбор качества для callback `tdq:` (producer — tool)."""
    now = time.monotonic()
    _purge_stale_pending(now)
    _TOOL_DL_PENDING[(chat_id, user_id)] = {
        "url": url,
        "title": title,
        "qualities": tuple(qualities or ()),
        "trigger_message_id": trigger_message_id,
        "expires": now + _TOOL_DL_PENDING_TTL_SECONDS,
    }


def pop_tool_download_pending(chat_id: int, user_id) -> dict | None:
    """Забрать pending (одноразово). Нет/протух → None (callback «протухла»)."""
    now = time.monotonic()
    _purge_stale_pending(now)
    entry = _TOOL_DL_PENDING.pop((chat_id, user_id), None)
    if entry is None or entry.get("expires", 0) <= now:
        return None
    return entry


def peek_tool_download_pending(chat_id: int, user_id) -> dict | None:
    """Pending БЕЗ изъятия — валидация callback до consume (ревью-итер.1 L1).

    Позволяет отвергнуть подделанную/несуществующую высоту, не теряя pending
    и не снимая рабочую клавиатуру. Нет/протух → None.
    """
    now = time.monotonic()
    _purge_stale_pending(now)
    entry = _TOOL_DL_PENDING.get((chat_id, user_id))
    if entry is None or entry.get("expires", 0) <= now:
        return None
    return entry


def keywords(query: str) -> list[str]:
    """Токены запроса для FTS-поиска (L2-путь query_chat_memory)."""
    return _TOKEN_RE.findall(str(query or "").lower())


def _time_range_since(time_range: str) -> int:
    """Секунды с эпохи для окна (0 = без фильтра по времени)."""
    seconds = _TIME_RANGE_SECONDS.get((time_range or "all").strip().lower(), 0)
    return 0 if not seconds else int(time.time()) - seconds


def _history_depth(raw) -> int:
    """depth get_recent_history → int в [1, _HISTORY_MAX_DEPTH].

    Отсутствие/кривой тип → _HISTORY_DEFAULT_DEPTH; 0/отрицательное → 1
    (spec §2: «клампится в 1.._HISTORY_MAX_DEPTH»)."""
    if raw is None or raw == "":
        return _HISTORY_DEFAULT_DEPTH
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _HISTORY_DEFAULT_DEPTH
    return max(1, min(value, _HISTORY_MAX_DEPTH))


def _truncate(text: str, limit: int) -> str:
    """Обрезка результата до лимита символов."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _image_memory_note(request) -> str:
    """A4 (ADR-1026-19 D5/D6): reply-заметка tool-пути (уточнение/
    дисклеймер/запрос фото) — только при memory-aware запросе.

    F2 (T-3640): `exact_likeness` — независимый интент-сигнал, поэтому
    заметка эмитится при `context_required OR exact_likeness` (иначе
    exact-запрос с неразрешённым субъектом молча терял ветку фото/референса)."""
    if request is None:
        return ""
    mc = getattr(request, "memory_context", None)
    exact = bool(mc.get("exact_likeness")) if isinstance(mc, dict) else False
    if not (bool(getattr(request, "context_required", False)) or exact):
        return ""
    try:
        return image_context_memory.build_reply_note(mc)
    except Exception:  # pragma: no cover
        return ""


def _dig_json_payload(result: dict, limit: int) -> str:
    """S10.20-3: сериализовать dig-контракт, ужимая СЕКЦИИ по бюджету.

    ``_truncate(json.dumps(...))`` рвал JSON (невалидные скобки). Здесь
    сначала выкидываются хвостовые элементы ``snippets``/``facts``, затем
    укорачиваются самые длинные строки — итог ВСЕГДА валидный JSON. При
    усечении добавляется ``"truncated": true`` (честный сигнал модели)."""
    budget = max(1, int(limit or 0))
    payload = json.dumps(result, ensure_ascii=False)
    if len(payload) <= budget:
        return payload
    out = dict(result)
    out["snippets"] = list(result.get("snippets") or [])
    out["facts"] = list(result.get("facts") or [])
    out["truncated"] = True

    def _size() -> int:
        return len(json.dumps(out, ensure_ascii=False))

    # 1) выкидываем хвостовые элементы секций (сначала facts — они дешевле).
    while _size() > budget and (out["snippets"] or out["facts"]):
        if out["facts"]:
            out["facts"].pop()
        else:
            out["snippets"].pop()
    # 2) усекаем самые длинные строки (валидность JSON сохраняется).
    for _ in range(100):
        if _size() <= budget:
            break
        target = out["snippets"] if out["snippets"] else out["facts"]
        if not target:
            break
        idx = max(range(len(target)), key=lambda k: len(str(target[k])))
        text = str(target[idx])
        if len(text) <= 1:
            break
        overshoot = _size() - budget
        target[idx] = text[:max(1, len(text) - overshoot - 8)]
    serialized = json.dumps(out, ensure_ascii=False)
    if len(serialized) > budget:
        # Даже метаданные не влезли — честный минимум (JSON валиден).
        serialized = json.dumps(
            {"truncated": True,
             "total_mentions": int(result.get("total_mentions") or 0)},
            ensure_ascii=False)
    return serialized


async def resolve_lore_compiler_flag(chat_id: int | None) -> bool:
    """S10.20-2: флаг «Летописца» тем же per-chat каскадом, что DirectChat
    (override → hot → канон). ``chat_id=None`` — глобальный hot-слой."""
    base = hot.get("flags.lore_compiler_enabled",
                   settings.LORE_COMPILER_ENABLED)
    if chat_id is None:
        return bool(base)
    try:
        from services.chat_params import get_chat_param
        value = await get_chat_param(
            chat_id, "flags.lore_compiler_enabled", base)
        return bool(value)
    except Exception:
        logger.warning("[tools] lore flag resolve failed — global | chat=%s",
                       chat_id)
        return bool(base)


def _format_timestamp(ts) -> str:
    """timestamp (int/float) → 'YYYY-MM-DD HH:MM' (пусто при отсутствии)."""
    if not ts:
        return ""
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return ""


class ToolHealthDeps:
    """Контейнер health-инструмента: CheckupService + CheckupLogsFetcher.

    Инжектится из bot.py (тот же путь, что роутер 0g), чтобы инструмент
    get_bot_health не тянул хендлер в сервисный слой.
    """

    def __init__(self, service, fetcher) -> None:
        self.service = service            # CheckupService
        self.fetcher = fetcher            # CheckupLogsFetcher


class ToolDeps:
    """Контейнер зависимостей инструментов (инжектится из bot.py).

    Раунд 10.15 (F8): video/downloader/health/db — аддитивные keyword-only
    (старые вызовы `ToolDeps(search, memory, aliases)` не ломаются).
    """

    def __init__(self, search, memory, aliases=None, *, video=None,
                 downloader=None, health=None, db=None,
                 download_cooldown=None, llm=None, transcriber=None,
                 extractor=None) -> None:
        self.search = search            # SearchAggregator
        self.memory = memory            # MemoryManager
        self.aliases = aliases          # AliasResolver | None
        self.video = video              # YoutubeSummarizerService | None
        self.downloader = downloader    # VideoDownloader | None
        self.health = health            # ToolHealthDeps | None
        self.db = db                    # Database | None (F9)
        # R10.15-9: zero-arg-провайдер общего download-кулдауна роутера 4e
        # (ленивая ссылка: `setup_video_download` пересоздаёт трекер в
        # on_startup уже после сборки ToolDeps). None → гейта нет.
        self.download_cooldown = download_cooldown
        # Раунд 10.20 (БЛОК 1, ADR-1020-4 п.3, T-1887): LLM-клиент для
        # изолированного синтеза истории «Летописца» (compile_lore_story).
        # None → инструмент честно вернёт «сервис недоступен».
        self.llm = llm                  # LLMClient | None
        # Раунд 10.24 (F14, ADR-1024-15 §2.3): STT-сервис для нативного
        # пути summarize_video (STT-фолбэк выжимки). Тот же инстанс, что у
        # youtube/voice (DI в bot.py). None → честная деградация.
        self.transcriber = transcriber  # VoiceTranscriber | None
        # Раунд 10.26 (A2, ADR-1026-15 D5): extractor для `fetch_article`
        # (reuse `WebContentExtractor`; тот же инстанс, что у web-модуля).
        # None → инструмент честно вернёт структурный error.
        self.extractor = extractor      # WebContentExtractor | None


class ToolContext:
    """Контекст вызова инструментов (одно сообщение direct_chat).

    Раунд 10.15 (F8): bot/reply_to_message_id/user_id — аддитивные
    keyword-only (у download_media есть куда отправить файл и на что
    ответить реплаем).

    Раунд 10.20 (БЛОК 1, ADR-1020-6 п.2, T-1887/T-1892): ``lore_compiled`` —
    детерминированный СИГНАЛ РЕЖИМА. Ставится инструментом
    compile_lore_story (успешный синтез) и читается DirectChat ПОСЛЕ цикла
    `chat_with_tools`: `True` → доставка истории локально с parse_mode=HTML
    (О5), иначе — обычный plain-путь байт-в-байт. Сам цикл (`tool_loop.py`)
    сигнал НЕ обрабатывает — он лишь проносит ctx.
    """

    def __init__(self, chat_id: int, query: str, *, bot=None,
                 reply_to_message_id=None, user_id=None,
                 lore_verbatim_instruction: bool = True,
                 correlation_id: str | None = None,
                 native_media=None,
                 resolved_url: str | None = None,
                 image_request_handled: bool = False) -> None:
        self.chat_id = chat_id
        self.query = str(query or "")
        self.bot = bot
        self.reply_to_message_id = reply_to_message_id
        self.user_id = user_id
        # F7 (ADR-1023-7 D4): сквозной id ответа — прокидывается в
        # инструменты, которые пишут телеметрию (generate_image → step='image').
        self.correlation_id = correlation_id
        # Раунд 10.24 (F14, ADR-1024-15 §2.3): разрешённый aiogram-объект
        # нативного медиа (``native_media.NativeMedia`` | None). Заполняется
        # DirectChat (F13), потребляется нативным путём инструментов (F14).
        self.native_media = native_media
        # Раунд 10.26 (A2, ADR-1026-15 D6): общий контекстный резолв ссылки
        # (текущее сообщение → reply). `fetch_article` без `url` берёт её
        # отсюда; None → честный `no_url`.
        self.resolved_url = str(resolved_url or "").strip() or None
        # A3 (ADR-1026-16 D3): авторитетный маркер прогона «изображение уже
        # обработано на этом ходу» (срабатывание пре-гейта ключевика →
        # direct_chat_service прокидывает image_pre_gate_fired). Читается
        # _generate_image ПЕРВЫМ делом → skipped/already_handled не сгенерирует.
        self.image_request_handled = bool(image_request_handled)
        # Раунд 10.26 (A2, ADR-1026-15 D1): out-of-band envelope-журнал
        # прогона (структурные результаты/ошибки/лимиты) — программный
        # A→B-handoff для инструментов и Синтезатора. В модельный ввод НЕ
        # сериализуется.
        self.tool_results: list[dict] = []
        self.lore_compiled = False
        # Раунд 10.20 (БЛОК 7.2c, ADR-1020-7 §2, T-1922): готовый текст
        # истории «Летописца» (HTML). DirectChat при `lore_compiled` доставляет
        # его детерминированно, не полагаясь на «верни дословно».
        self.lore_story = ""
        # S10.20-4: служебная инструкция «верни story ДОСЛОВНО» нужна только
        # DirectChat (там сигнал доставки уже есть, это мягкая страховка).
        # В фактчеке она провоцировала вердикт-историю → caller ставит False.
        self.lore_verbatim_instruction = bool(lore_verbatim_instruction)

    def result_for(self, tool_name: str) -> dict | None:
        """A2 (ADR-1026-15 D1/D6): последний envelope-результат инструмента.

        Общий (не per-combination) программный handoff A→B: инструмент B
        (или Синтезатор) может прочитать структурный результат A. Возвращает
        envelope-запись или ``None`` (инструмент не вызывался).
        """
        for entry in reversed(getattr(self, "tool_results", []) or []):
            if entry.get("tool") == tool_name:
                return entry
        return None


# ── dig_into_lore (раунд 9, T-820): код-дефолты (spec §3.6.4; REGISTRY-ключи
# flags.dig_*/limits.dig_* заведены фикс-раундом — группы flags_memory/
# limits_memory; код читает через hot.get с фолбэком settings, код-константы
# ниже — только страховка для пустого значения).
_DIG_YEAR_MIN = 2000
_DIG_PERSON_MAX_CHARS = 100
# «N лет назад» в query без year (major-2/D-fix): слова-количества → N.
_DIG_YEARS_AGO_NUM_RE = re.compile(
    r"(\d{1,2})\s+(?:лет|год(?:а)?)\s+назад")
_DIG_YEARS_AGO_WORD_RE = re.compile(
    r"(несколько|пару|тройку)\s+лет\s+назад")
_DIG_YEARS_AGO_WORDS = {"несколько": 3, "пару": 2, "тройку": 3}
# Верхний предел глубины BFS по графу (защита от кривого hot-значения).
_DIG_GRAPH_MAX_HOP_DEPTH = 5


class ToolRouter:
    """Реестр исполнения инструментов (3.3). Никогда не бросает."""

    def __init__(self, deps: ToolDeps) -> None:
        self.deps = deps

    async def dispatch(self, name: str, arguments: dict, ctx: ToolContext) -> str:
        """→ строка результата инструмента (в т.ч. 'ОШИБКА …') — НЕ бросает."""
        registry = {
            "execute_web_search": self._execute_web_search,
            "query_chat_memory": self._query_chat_memory,
            "dig_into_lore": self._dig_into_lore,
            "summarize_video": self._summarize_video,
            "download_media": self._download_media,
            "get_bot_health": self._get_bot_health,
            "get_recent_history": self._get_recent_history,
            "compile_lore_story": self._compile_lore_story,
            "generate_image": self._generate_image,
            "transcribe_video": self._transcribe_video,
            "fetch_article": self._fetch_article,
            "get_user_context": self._get_user_context,
        }
        method = registry.get(name)
        if method is None:
            logger.warning("[tools] unknown tool | name=%s", name)
            return f"ОШИБКА: неизвестный инструмент {name}"
        try:
            return await method(arguments, ctx)
        except Exception as exc:
            # R17: только класс исключения (без str(exc) — он может нести
            # URL/секреты; ревью-итер.1 L7).
            logger.warning("[tools] exec failed | tool=%s | error=%s",
                           name, type(exc).__name__)
            return f"ОШИБКА {name}: {type(exc).__name__}"

    # ── execute_web_search ────────────────────────────────────────

    async def _execute_web_search(self, arguments: dict, ctx: ToolContext) -> str:
        query = self._require_query(arguments, ctx)
        try:
            text = await asyncio.wait_for(
                self.deps.search.search(query, max_symbols=_SEARCH_MAX_SYMBOLS),
                timeout=_SEARCH_TOOL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return ("ОШИБКА execute_web_search: поиск недоступен (timeout)")
        except AllSearchEnginesFailedException as exc:
            return f"ОШИБКА execute_web_search: поиск недоступен ({exc})"
        except Exception as exc:      # FR-11: любой сбой — структурированный текст
            logger.warning("[tools] web search failed | query=%r | error=%s",
                           query, f"{type(exc).__name__}: {exc}")
            return (f"ОШИБКА execute_web_search: поиск недоступен "
                    f"({type(exc).__name__})")
        if not text or not str(text).strip():
            return f"ОШИБКА execute_web_search: поиск недоступен (empty result)"
        return f"Результаты поиска по запросу «{query}»:\n{_truncate(text, _SEARCH_MAX_SYMBOLS)}"

    # ── query_chat_memory ─────────────────────────────────────────

    async def _query_chat_memory(self, arguments: dict, ctx: ToolContext) -> str:
        query = self._require_query(arguments, ctx)
        time_range = str(arguments.get("time_range") or "all")
        if time_range not in _TIME_RANGE_SECONDS:
            time_range = "all"
        since = _time_range_since(time_range)
        lines: list[str] = []

        # 1. FTS по L1-сообщениям (search_long_term) с пост-фильтром окна.
        rows = await self.deps.memory.search_long_term(
            ctx.chat_id, keywords(query), limit=_MEMORY_FTS_LIMIT)
        # T-678 (прод-лог): реальные строки — aiosqlite.Row, у которого НЕТ
        # .get (AttributeError в проде) → нормализация в dict ДО обработки.
        rows = [dict(row) for row in rows]
        for row in rows:
            ts = _format_timestamp(row.get("timestamp"))
            if since and int(row.get("timestamp") or 0) < since:
                continue
            name = self._resolve_name(row)
            stamp = f" [{ts}]" if ts else ""
            text = str(row.get("text") or "").strip()
            if text:
                lines.append(f"[{name}{stamp}]: {text}")

        # 1b. Счётчик + диапазон дат (best-effort; ошибка не роняет результат).
        stats = None
        try:
            stats = await self.deps.memory.count_mentions(
                ctx.chat_id, keywords(query), since_ts=since)
        except Exception:
            logger.warning("[tools] query_chat_memory count failed | query=%r",
                           query, exc_info=True)
        if isinstance(stats, dict) and stats.get("count"):
            logger.info("[tools] query_chat_memory | query=%r | count=%d | since_ts=%d",
                        query, stats["count"], since)

        # 2. Векторный поиск по фактам архива/графа (только широкие окна).
        if not lines and time_range in ("last_month", "all"):
            facts = await self.deps.memory.vector_search(
                ctx.chat_id, query, limit=_MEMORY_VEC_LIMIT)
            lines.extend(str(fact).strip() for fact in facts if str(fact).strip())

        # 3. Гибридный RAG-контекст, если всё ещё пусто.
        if not lines:
            # 10.20 (БЛОК 2.6, ADR-1020-2): ASC-хронология перед рендером.
            rag = await self.deps.memory.get_rag_context(
                ctx.chat_id, query, sort_by_timestamp=True)
            if rag and str(rag).strip():
                lines.append(str(rag).strip())

        if not lines and not (isinstance(stats, dict) and stats.get("count")):
            return f"По запросу «{query}» в памяти ничего не найдено."
        parts: list[str] = []
        if isinstance(stats, dict) and stats.get("count"):
            period = _TIME_RANGE_LABELS.get(time_range, "за всё время")
            stamp = ""
            if stats.get("first_seen") or stats.get("last_seen"):
                first = _format_timestamp(stats.get("first_seen"))
                last = _format_timestamp(stats.get("last_seen"))
                if first and last and first != last:
                    stamp = f" (с {first} по {last})"
            parts.append(f"Найдено {stats['count']} упоминаний «{query}» {period}{stamp}")
        parts.extend(lines)
        return _truncate("\n".join(parts), _MEMORY_MAX_SYMBOLS)

    # ── dig_into_lore (раунд 9, AGI Memory T-820, spec §3.2.1/Q6) ────────

    async def _dig_into_lore(self, arguments: dict, ctx: ToolContext) -> str:
        """Глубокое копание в историю чата: FTS5-сниппеты L1 с датами
        (mode messages/both) + факты графа (mode facts/both); пост-фильтры
        периода (year / «N лет назад» из query) и участника (person, с
        расширением именами из граф-обхода nodes/edges). НЕ бросает: ошибка
        этапа → WARNING, секция пуста; всё пусто → «ничего не нашёл по
        запросу»; флаг flags.dig_enabled=false → строка отключения."""
        if not hot.get("flags.dig_enabled", settings.DIG_ENABLED):
            return "Инструмент dig_into_lore отключен."
        query = self._require_query(arguments, ctx)
        mode = str(arguments.get("mode") or "both").strip().lower()
        if mode not in ("messages", "facts", "both"):
            logger.warning("[tools] dig mode invalid - default 'both' | "
                           "mode=%r", mode)
            mode = "both"
        year = self._dig_year(arguments.get("year"))
        if year is None:
            # major-2(а): query «(\d+|несколько|пару) лет назад» без year →
            # год = now.year − N (spec §3.2.1 п.3(б), фикс-раунд).
            year = self._dig_year_from_query(query)
        bounds = self._year_bounds(year) if year is not None else None
        if year is not None and bounds is None:
            logger.warning("[tools] dig year вне диапазона | year=%s", year)
        person = self._dig_person_text(arguments.get("person"))
        person_uid, person_terms = self._dig_person_terms(person)
        tokens = keywords(query)
        # Имена-формы (person) расширяют запрос OR-токенами (spec п.2).
        merged = list(dict.fromkeys(tokens + person_terms))
        # major-2(б): имена из граф-обхода (BFS по nodes/edges глубиной
        # limits.dig_graph_hop_depth; фолбэк target_user) — источник ИМЁН
        # для FTS (spec п.4; best-effort, пусто при любой ошибке).
        graph_names = await self._dig_graph_names(
            ctx, person_terms if person is not None else tokens)
        if graph_names:
            for name in graph_names:
                for word in keywords(name):
                    if len(word) >= 3 and word not in merged:
                        merged.append(word)
                if len(merged) >= 40:
                    break

        dig_max_symbols = int(hot.get("limits.dig_max_symbols",
                                      settings.DIG_MAX_SYMBOLS)
                              or settings.DIG_MAX_SYMBOLS)
        max_snippets = int(hot.get("limits.dig_max_snippets",
                                   settings.DIG_MAX_SNIPPETS)
                           or settings.DIG_MAX_SNIPPETS)
        max_facts = int(hot.get("limits.dig_max_facts",
                                settings.DIG_MAX_FACTS)
                        or settings.DIG_MAX_FACTS)

        msg_lines: list[str] = []
        fact_lines: list[str] = []
        stage_error = None
        total_mentions = 0
        mentions_by_authors: dict[str, int] = {}
        first_seen = None
        last_seen = None
        if not merged:
            return self._dig_not_found(query)
        # (в) mode messages/both: FTS5 по smart_messages (search_long_term) +
        #     пост-фильтр периода/user_id; рендер «[Имя YYYY-MM-DD]: текст».
        if mode in ("messages", "both"):
            try:
                rows = await self.deps.memory.search_long_term(
                    ctx.chat_id, merged, limit=_MEMORY_FTS_LIMIT)
                rows = [dict(row) for row in rows]     # T-678: aiosqlite.Row
                seen: set[str] = set()
                for row in rows:
                    ts = int(row.get("timestamp") or 0)
                    if bounds and not (bounds[0] <= ts <= bounds[1]):
                        continue
                    if person_uid is not None and \
                            int(row.get("user_id") or 0) != person_uid:
                        continue
                    text = str(row.get("text") or "").strip()
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    name = self._resolve_name(row)
                    # 10.20 (БЛОК 2.8, ADR-1020-2 п.2): канонический рендер
                    # строки контекста (§2.2, kind="msg") — дата ВРЕМЯ | автор
                    # | ID (tg:→msg:) | Переслано.
                    item_id = resolve_item_id(
                        tg_message_id=row.get("tg_message_id"),
                        message_id=row.get("id"))
                    forward_source = (row.get("forward_source")
                                      if row.get("is_forward") else None)
                    msg_lines.append(format_context_item(
                        ts=ts, author=name, item_id=item_id,
                        forward_source=forward_source, text=text, kind="msg"))
                    if len(msg_lines) >= max_snippets:
                        break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stage_error = f"{type(exc).__name__}"
                logger.warning("[tools] dig messages failed | query=%r | "
                               "error=%s", query, stage_error, exc_info=True)
        # (г) mode facts/both: FTS по graph_facts (v7-совместимо: колонки v8
        #     не используются); пост-фильтр периода и target_user (person).
        if mode in ("facts", "both"):
            try:
                db = getattr(self.deps.memory, "db", None)
                if db is not None and hasattr(db, "search_graph_facts_fts"):
                    from services.summary_memory import (
                        _stale_suffix,
                        build_fts_query,
                    )
                    match = build_fts_query(merged)
                    if match:
                        # F2/T-1426 (spec §2): dig_into_lore — прямое копание,
                        # архивные beliefs участвуют (include_archived=True).
                        rows = await db.search_graph_facts_fts(
                            ctx.chat_id, match,
                            limit=max_facts * 3,
                            now_ts=int(time.time()),
                            include_direct_reply=False,
                            include_archived=True)
                        seen_facts: set[str] = set()
                        for row in (dict(r) for r in rows):
                            ts = int(row.get("rag_ts") or 0)
                            if bounds and not (bounds[0] <= ts <= bounds[1]):
                                continue
                            if person is not None:
                                target = str(row.get("target_user") or "").strip()
                                if not target or not any(
                                        term in target.casefold()
                                        for term in person_terms):
                                    continue
                            text = str(row.get("fact") or "").strip()
                            if not text or text in seen_facts:
                                continue
                            seen_facts.add(text)
                            # 10.20 (БЛОК 2.8, ADR-1020-2 п.2): единый
                            # канонический рендер факта (§2.2, kind="fact"):
                            # «[ММ.ГГГГ | Автор | fact:ID]: текст (+ устарело)».
                            # Автор — target_user строки (R16, не выдумываем).
                            ts_render = ts if ts else None
                            fact_lines.append(format_context_item(
                                ts=ts_render,
                                author=row.get("target_user"),
                                item_id=resolve_item_id(
                                    fact_id=row.get("id")),
                                text=text, kind="fact",
                                stale=bool(_stale_suffix(ts_render))))
                            if len(fact_lines) >= max_facts:
                                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stage_error = f"{type(exc).__name__}"
                logger.warning("[tools] dig facts failed | query=%r | "
                               "error=%s", query, stage_error, exc_info=True)
        # (д) 10.20 (БЛОК 2.8, ADR-1020-2 п.2): агрегация упоминаний по
        # авторам — GROUP BY в SQL, имя резолвится тем же R16-каскадом
        # (_resolve_name). Считается по окну year (since/until). Ошибка
        # счётчика не роняет выдачу: total_mentions честно молчит (R16).
        if mode in ("messages", "both") and merged:
            try:
                db = getattr(self.deps.memory, "db", None)
                counter = getattr(
                    db, "search_messages_fts_count_by_author", None)
                from services.summary_memory import build_fts_query
                match = build_fts_query(merged)
                if callable(counter) and match:
                    stats = await counter(
                        ctx.chat_id, match,
                        since_ts=bounds[0] if bounds else 0,
                        until_ts=bounds[1] if bounds else 0)
                    total_mentions = int(stats.get("count") or 0)
                    for entry in stats.get("by_author") or []:
                        name = self._resolve_name(entry)
                        mentions_by_authors[name] = (
                            mentions_by_authors.get(name, 0)
                            + int(entry.get("count") or 0))
                    first_seen = _format_timestamp(stats.get("first_seen"))
                    last_seen = _format_timestamp(stats.get("last_seen"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("[tools] dig count failed | query=%r | "
                               "error=%s", query, type(exc).__name__)
        if not msg_lines and not fact_lines and not total_mentions:
            if stage_error:
                return (f"ОШИБКА dig_into_lore: этап поиска не выполнен "
                        f"({stage_error})")
            return self._dig_not_found(query)
        result = {
            "total_mentions": total_mentions,
            "mentions_by_authors": mentions_by_authors,
            "first_seen": first_seen or None,
            "last_seen": last_seen or None,
            "snippets": msg_lines,
            "facts": fact_lines,
        }
        return _dig_json_payload(result, dig_max_symbols)

    # ── F8 (раунд 10.15, ADR-1015-3): новые инструменты ──────────────

    async def _summarize_video(self, arguments: dict, ctx: ToolContext) -> str:
        """Выжимка видео (F14, ADR-1024-15 §2.3/§4.5; UPD5 — только
        саммаризация, без `mode`). Источник: http(s)-`url` → ссылочный путь
        (YouTube → каскад; иная ссылка → мультимодальная выжимка); иначе
        нативное видео из `ctx.native_media` (видео-document) → tmp →
        публикация `media_share` + L1/L2 → STT-фолбэк выжимки. Нет источника →
        понятная ОШИБКА. Результат усечён до `_MEMORY_MAX_SYMBOLS`.
        R17: URL/пути не логируются."""
        source, url, native = self._resolve_tool_source(arguments, ctx)
        if source is None:
            # F14 §2.5: OFF → прежняя (до-F14) строка ошибки; ON → понятная
            # «нет источника» (нужна ссылка или видео из реплая).
            if not _native_tools_enabled():
                return "ОШИБКА summarize_video: некорректная ссылка"
            return ("ОШИБКА summarize_video: нет источника "
                    "(нужна ссылка или видео из реплая)")
        service = self.deps.video
        if service is None:
            return "ОШИБКА summarize_video: сервис недоступен"
        try:
            if source == "link":
                text = await asyncio.wait_for(
                    self._video_summary(service, url, ctx),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
            else:
                text = await asyncio.wait_for(
                    self._video_native_summary(service, ctx, native),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] summarize_video timeout | source=%s",
                           source)
            return "ОШИБКА summarize_video: timeout"
        except Exception as exc:
            logger.warning("[tools] summarize_video failed | source=%s | "
                           "error=%s", source, type(exc).__name__)
            return f"ОШИБКА summarize_video: {type(exc).__name__}"
        text = str(text or "").strip()
        if not text:
            return "ОШИБКА summarize_video: пустой результат"
        return _truncate(text, _MEMORY_MAX_SYMBOLS)

    @staticmethod
    async def _video_transcript(service, url: str) -> str:
        """Субтитры YouTube (cap). F14 сохраняет хелпер для F19
        (`transcribe_video`); ссылочный STT/direct — зона F19."""
        video_id = extract_youtube_video_id(url)
        if video_id is None:
            raise ValueError("transcript доступен только для YouTube")
        return await service.engine.fetch_transcript(
            video_id, _SUMMARIZE_TRANSCRIPT_CAP, on_retry=None)

    @staticmethod
    async def _video_summary(service, url: str, ctx: ToolContext) -> str:
        """Ссылочная выжимка: YouTube → каскад выжимки по video_id;
        прямая/платформа → мультимодальная выжимка по video_url."""
        video_id = extract_youtube_video_id(url)
        if video_id is not None:
            return await service.summarize_cascade(video_id,
                                                   chat_id=ctx.chat_id)
        return await service.summarize_media_url(chat_id=ctx.chat_id,
                                                 video_url=url)

    async def _video_native_summary(self, service, ctx: ToolContext,
                                    native) -> str:
        """Нативная выжимка (F14, ADR-1024-15 §2.3): tmp-файл → публикация
        `media_share` → L1/L2 (`summarize_media_url`); при недоступности/пустом
        результате — STT-фолбэк выжимки (`deps.transcriber` +
        `summarize_transcript`). tmp чистится в finally. R17: без URL/путей."""
        path = None
        text = ""
        try:
            path = await native_media.download_to_tmp(
                ctx.bot, native, timeout=_DOWNLOAD_TOOL_TIMEOUT)
            video_client = getattr(service, "video_client", None)
            if (video_client is not None
                    and getattr(video_client, "available", False)
                    and media_share.enabled()):
                ttl = int(hot.get("limits.media_share_ttl_seconds",
                                  settings.MEDIA_SHARE_TTL_SECONDS) or 0)
                ticket = await media_share.publish_media_file(str(path), ttl)
                if ticket is not None:
                    try:
                        text = await service.summarize_media_url(
                            chat_id=ctx.chat_id, video_url=ticket.abs_url,
                            label="tg-file")
                    except Exception as exc:
                        logger.warning("[tools] native summarize L1/L2 "
                                       "unavailable — STT fallback | error=%s",
                                       type(exc).__name__)
                        text = ""
                    finally:
                        await media_share.delete_file(ticket.file_id)
            if not str(text or "").strip():
                transcript = await self._native_stt(path, native)
                text = await service.summarize_transcript(
                    chat_id=ctx.chat_id, transcript=transcript)
            return text
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def _native_stt(self, path, native) -> str:
        """STT нативного видео-файла (F14): `deps.transcriber.transcribe_voice`
        с видео-расширением; нет сервиса → RuntimeError (dispatch → ОШИБКА).
        Таймаут — паритет youtube (`limits.video_stt_timeout_seconds`)."""
        transcriber = getattr(self.deps, "transcriber", None)
        if transcriber is None:
            raise RuntimeError("transcriber unavailable")
        ext = native_media.media_suffix(native).lstrip(".") or "mp4"
        timeout = float(hot.get("limits.video_stt_timeout_seconds",
                                settings.VIDEO_STT_TIMEOUT_SECONDS)
                        or settings.VIDEO_STT_TIMEOUT_SECONDS)
        return await transcriber.transcribe_voice(
            str(path), ext, timeout=timeout)

    # ── F19 (раунд 10.24, ADR-1024-20): transcribe_video (сырой текст) ──

    async def _transcribe_video(self, arguments: dict,
                                ctx: ToolContext) -> str:
        """Сырая транскрибация (F19, ADR-1024-20 §2.2/§2.5): дословный текст
        БЕЗ пересказа. Источник: http(s)-``url`` → ссылочный путь (YouTube →
        субтитры raw, иначе download+STT); иначе нативное медиа из
        ``ctx.native_media`` (video/document/voice/video_note) → fetch → STT.
        Нет источника → понятная ОШИБКА. Результат усечён до
        ``_MEMORY_MAX_SYMBOLS``. НИКОГДА не бросает (контракт dispatch).
        R17: только ``source``/``kind``/``out_chars``/``error=<Class>``."""
        source, url, native = self._resolve_tool_source(
            arguments, ctx, kinds=native_media.MEDIA_KINDS)
        if source is None:
            return ("ОШИБКА transcribe_video: нет источника "
                    "(нужна ссылка или медиа из реплая)")
        kind = getattr(native, "kind", "") if source == "native" else "link"
        try:
            if source == "link":
                text = await asyncio.wait_for(
                    self._link_transcript(url),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
            else:
                text = await asyncio.wait_for(
                    self._native_transcript(ctx, native),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] transcribe_video timeout | source=%s | "
                           "kind=%s", source, kind)
            return "ОШИБКА transcribe_video: timeout"
        except Exception as exc:
            logger.warning("[tools] transcribe_video failed | source=%s | "
                           "kind=%s | error=%s", source, kind,
                           type(exc).__name__)
            return f"ОШИБКА transcribe_video: {type(exc).__name__}"
        text = str(text or "").strip()
        if not text:
            logger.info("[tools] transcribe_video | source=%s | kind=%s | "
                        "out_chars=0", source, kind)
            return "ОШИБКА transcribe_video: пустой результат"
        truncated = _truncate(text, _MEMORY_MAX_SYMBOLS)
        logger.info("[tools] transcribe_video | source=%s | kind=%s | "
                    "out_chars=%d", source, kind, len(truncated))
        return truncated

    async def _link_transcript(self, url: str) -> str:
        """Ссылочный путь: YouTube → субтитры raw (cap); при недоступности
        субтитров (или для direct/platform) → download+STT. R17: без URL в
        логах (только класс ошибки)."""
        video_id = extract_youtube_video_id(url)
        if video_id is not None and self.deps.video is not None:
            try:
                return await self._video_transcript(self.deps.video, url)
            except Exception as exc:
                logger.warning(
                    "[tools] transcribe_video subtitles unavailable — "
                    "download+STT | error=%s", type(exc).__name__)
        return await self._link_stt(url)

    async def _link_stt(self, url: str) -> str:
        """direct/platform (и YouTube-фолбэк): download → STT raw. tmp-файл
        удаляется в finally. R17: без URL/путей в логах."""
        downloader = getattr(self.deps, "downloader", None)
        if downloader is None:
            raise RuntimeError("downloader unavailable")
        path = await asyncio.wait_for(
            downloader.download(url, None), timeout=_DOWNLOAD_TOOL_TIMEOUT)
        try:
            return await self._stt_media(path, _path_ext(path))
        finally:
            try:
                path.unlink(missing_ok=True)
            except (OSError, AttributeError):
                pass

    async def _native_transcript(self, ctx: ToolContext, native) -> str:
        """Нативный путь (F19): ``download_to_tmp`` → STT raw. tmp чистится в
        finally. R17: без file_id/путей в логах."""
        path = None
        try:
            path = await native_media.download_to_tmp(
                ctx.bot, native, timeout=_DOWNLOAD_TOOL_TIMEOUT)
            return await self._stt_media(
                path, native_media.media_suffix(native).lstrip(".") or "mp4")
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def _stt_media(self, path, ext: str) -> str:
        """STT файла ``deps.transcriber`` (F19): нет сервиса → RuntimeError
        (dispatch → ОШИБКА). Таймаут — паритет youtube
        (``limits.video_stt_timeout_seconds``)."""
        transcriber = getattr(self.deps, "transcriber", None)
        if transcriber is None:
            raise RuntimeError("transcriber unavailable")
        timeout = float(hot.get("limits.video_stt_timeout_seconds",
                                settings.VIDEO_STT_TIMEOUT_SECONDS)
                        or settings.VIDEO_STT_TIMEOUT_SECONDS)
        return await transcriber.transcribe_voice(str(path), ext,
                                                  timeout=timeout)

    # ── fetch_article (A2, раунд 10.26, ADR-1026-15 D5) ──────────────────

    async def _fetch_article(self, arguments: dict, ctx: ToolContext) -> str:
        """Извлечение статьи по URL → JSON `{status,url,source_id,chars,
        truncated,markdown[,title]}` (ADR-1026-15 D5). Источник: http(s)-
        ``url`` аргумента; иначе общий ``ctx.resolved_url`` (D6). Reuse
        ``WebContentExtractor.extract`` (каскад trafilatura→Tavily→Exa); НЕ
        второй контур (тот же роутер/`tool_loop`/`ToolDeps`). НИКОГДА не
        бросает (контракт dispatch). R17: в логи — только ``source``/``chars``/
        класс ошибки, без URL/текста/заголовка."""
        args = arguments if isinstance(arguments, dict) else {}
        raw_url = str(args.get("url") or "").strip()
        source = "argument"
        if raw_url:
            candidates = extract_urls(raw_url)    # reuse smartmodule_urls
            url = candidates[0] if candidates else ""
        else:
            source = "context"
            url = str(getattr(ctx, "resolved_url", "") or "").strip()
        if not url:
            # Честный no_url: нет ссылки в аргументах и однозначной в контексте.
            return json.dumps({"status": "error", "error": "no_url"},
                              ensure_ascii=False)
        source_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        extractor = getattr(self.deps, "extractor", None)
        if extractor is None:
            return json.dumps({"status": "error",
                               "error": "service_unavailable",
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        try:
            text = await asyncio.wait_for(
                extractor.extract(url, _ARTICLE_MAX_SYMBOLS),
                timeout=_ARTICLE_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] fetch_article timeout | source=%s", source)
            return json.dumps({"status": "error", "error": "timeout",
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        except WebContentExtractionFailedException as exc:
            logger.warning("[tools] fetch_article failed | source=%s | error=%s",
                           source, type(exc).__name__)
            return json.dumps({"status": "error", "error": "extract_failed",
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        except Exception as exc:
            logger.warning("[tools] fetch_article failed | source=%s | error=%s",
                           source, type(exc).__name__)
            return json.dumps({"status": "error", "error": type(exc).__name__,
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        markdown = str(text or "")
        chars = len(markdown)
        if chars <= 0:
            return json.dumps({"status": "error", "error": "empty",
                               "url": url, "source_id": source_id},
                              ensure_ascii=False)
        truncated = chars >= _ARTICLE_MAX_SYMBOLS
        payload = {"status": "ok", "url": url, "source_id": source_id,
                   "chars": chars, "truncated": truncated,
                   "markdown": markdown}
        title = self._article_title(markdown)
        if title:
            payload["title"] = title
        logger.info("[tools] fetch_article | source=%s | chars=%d | "
                    "truncated=%s", source, chars, truncated)
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _article_title(markdown: str) -> str:
        """Best-effort заголовок статьи: первый markdown-заголовок `# …`."""
        for line in str(markdown or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                if title:
                    return title[:200]
        return ""

    # ── get_user_context (A6, раунд 10.26, ADR-1026-18 D1–D8) ───────────

    async def _get_user_context(self, arguments: dict,
                                ctx: ToolContext) -> str:
        """Structured memory lookup по инициативе LLM (ADR-1026-18).

        Единая точка: валидация аргументов (§52 п.14) → резолв субъекта
        существующим AliasResolver (`chat_id` — из ``ToolContext``, НЕ параметр
        модели, D2) → purpose-роутинг (D3; lazy RAG только general/speech_style)
        → envelope из 5 полей §33 (D4: facts/sources/confidence/time/no_data) →
        R17-лог (purpose/user_id/chat_id/count/latency/empty_reason). Read-only,
        reuse существующего досье/RAG (D9): НЕ второй резолвер/RAG/БД.
        НИКОГДА не бросает (контракт dispatch)."""
        started = time.monotonic()
        purpose = ""
        try:
            if not _memory_lookup_enabled():
                return self._memory_lookup_finish(
                    ctx, purpose, None, 0, started, "disabled",
                    {"status": "error", "error": "disabled"})
            args = arguments if isinstance(arguments, dict) else {}
            raw_purpose = str(args.get("purpose") or "").strip().lower()
            parsed, detail = self._memory_lookup_parse(args)
            if detail is not None:
                return self._memory_lookup_finish(
                    ctx, raw_purpose, None, 0, started, detail,
                    {"status": "error", "error": "invalid_arguments",
                     "detail": detail})
            purpose = parsed["purpose"]
            aliases = await self._memory_lookup_aliases(ctx)
            person = self._memory_lookup_resolve(parsed, aliases)
            payload = await self._memory_lookup_build(ctx, parsed, person)
            return self._memory_lookup_finish(
                ctx, purpose, person.get("user_id"),
                len(payload.get("facts") or []), started,
                str(payload.get("empty_reason") or ""), payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[tools] memory lookup failed | purpose=%s | "
                           "error=%s", purpose or "-", type(exc).__name__)
            return self._memory_lookup_finish(
                ctx, purpose, None, 0, started, "lookup_failed",
                {"status": "error", "error": "lookup_failed"})

    @staticmethod
    def _memory_lookup_finish(ctx, purpose, user_id, count, started,
                              empty_reason, payload) -> str:
        """R17-лог (только разрешённые поля) + JSON результата (кап 4000)."""
        latency = int((time.monotonic() - started) * 1000)
        label = purpose if purpose in _MEMORY_LOOKUP_PURPOSE_DEFAULTS else "-"
        logger.info(
            "[memory] lookup | purpose=%s | user_id=%s | chat_id=%s | "
            "count=%d | latency_ms=%d | empty_reason=%s",
            label, user_id if user_id is not None else "-",
            getattr(ctx, "chat_id", None), int(count), latency,
            empty_reason or "")
        return ToolRouter._memory_lookup_serialize(payload)

    @staticmethod
    def _memory_lookup_serialize(payload: dict) -> str:
        """JSON-строка результата в бюджете `_MEMORY_LOOKUP_RESULT_MAX_CHARS`.

        При переполнении честно урезаются хвостовые facts/sources (и тексты
        фактов) с ``truncated: true`` — валидный JSON сохраняется."""
        budget = _MEMORY_LOOKUP_RESULT_MAX_CHARS
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) <= budget:
            return text
        out = dict(payload)
        out["facts"] = list(payload.get("facts") or [])
        out["sources"] = list(payload.get("sources") or [])
        out["truncated"] = True

        def _size() -> int:
            return len(json.dumps(out, ensure_ascii=False))

        while out["facts"] and _size() > budget:
            out["facts"].pop()
            if out["sources"]:
                out["sources"].pop()
        for _ in range(100):
            if _size() <= budget or not out["facts"]:
                break
            idx = max(range(len(out["facts"])),
                      key=lambda k: len(str(out["facts"][k].get("text") or "")))
            item = out["facts"][idx]
            current = str(item.get("text") or "")
            if len(current) <= 1:
                break
            overshoot = _size() - budget
            item["text"] = current[:max(1, len(current) - overshoot - 8)]
        return json.dumps(out, ensure_ascii=False)

    @staticmethod
    def _memory_lookup_parse(arguments):
        """Валидация аргументов (§52 п.14/D2) → (parsed | None, detail | None).

        detail ∈ {missing_person, invalid_person, invalid_purpose,
        invalid_max_items}. НИКОГДА не бросает."""
        args = arguments if isinstance(arguments, dict) else {}
        raw_person = args.get("person")
        if raw_person is not None and not isinstance(raw_person, str):
            return None, "invalid_person"
        person = str(raw_person or "").strip()
        raw_uid = args.get("user_id")
        uid = None
        if raw_uid not in (None, ""):
            if isinstance(raw_uid, bool):
                return None, "invalid_person"
            try:
                uid = int(raw_uid)
            except (TypeError, ValueError):
                return None, "invalid_person"
        if not person and uid is None:
            return None, "missing_person"
        purpose = str(args.get("purpose") or "").strip().lower()
        if purpose not in _MEMORY_LOOKUP_PURPOSE_DEFAULTS:
            return None, "invalid_purpose"
        max_items = _MEMORY_LOOKUP_PURPOSE_DEFAULTS[purpose]
        raw_max = args.get("max_items")
        if raw_max not in (None, ""):
            if isinstance(raw_max, bool):
                return None, "invalid_max_items"
            try:
                value = int(raw_max)
            except (TypeError, ValueError):
                return None, "invalid_max_items"
            if value < 1:
                return None, "invalid_max_items"
            max_items = value
        max_items = min(int(max_items), _MEMORY_LOOKUP_MAX_ITEMS_HARD)
        return ({"person": person, "user_id": uid, "purpose": purpose,
                 "max_items": max_items}, None)

    async def _memory_lookup_aliases(self, ctx):
        """Существующий AliasResolver (deps.aliases) либо per-chat fail-open
        `build_alias_resolver` — второй резолвер НЕ создаётся (D9)."""
        aliases = getattr(self.deps, "aliases", None)
        if aliases is not None:
            return aliases
        try:
            from services.summary_aliases import build_alias_resolver
            return await build_alias_resolver(ctx.chat_id)
        except Exception:
            logger.warning("[tools] memory lookup aliases unavailable | "
                           "chat=%s", getattr(ctx, "chat_id", None))
            return None

    def _memory_lookup_resolve(self, parsed: dict, aliases) -> dict:
        """Идентичность субъекта (D2): user_id → AliasResolver; иначе alias-карта
        (коллизия одинаковых имён → ambiguous, без слияния фактов); иначе
        canon-имя для точечного чтения. Возврат: name/user_id/resolution/
        aliases/candidates."""
        uid = parsed.get("user_id")
        person = str(parsed.get("person") or "").strip().lstrip("@")
        mapping = (getattr(aliases, "_aliases", None)
                   if aliases is not None else None)
        if uid is None and person.isdigit():
            uid = int(person)
        if uid is not None:
            name = self._memory_lookup_resolve_name(aliases, uid, person)
            return {"name": name, "user_id": uid, "resolution": "resolved",
                    "aliases": self._memory_lookup_person_aliases(
                        mapping, uid, name),
                    "candidates": []}
        candidates = self._memory_lookup_alias_candidates(mapping, person)
        if len(candidates) > 1:
            return {"name": "", "user_id": None, "resolution": "ambiguous",
                    "aliases": [], "candidates": candidates}
        if len(candidates) == 1:
            uid = candidates[0]
            name = self._memory_lookup_resolve_name(aliases, uid, person)
            return {"name": name, "user_id": uid, "resolution": "resolved",
                    "aliases": self._memory_lookup_person_aliases(
                        mapping, uid, name),
                    "candidates": []}
        name = person
        if aliases is not None and hasattr(aliases, "canon_name"):
            try:
                name = str(aliases.canon_name(person) or person)
            except Exception:
                name = person
        return {"name": name, "user_id": None, "resolution": "resolved",
                "aliases": [], "candidates": []}

    @staticmethod
    def _memory_lookup_resolve_name(aliases, uid, fallback) -> str:
        if aliases is not None and hasattr(aliases, "resolve"):
            try:
                return str(aliases.resolve(int(uid), fallback or None, None))
            except Exception:
                pass
        return str(fallback or uid)

    @staticmethod
    def _memory_lookup_alias_candidates(mapping, person) -> list:
        if not isinstance(mapping, dict) or not person:
            return []
        low = str(person).casefold()
        out: list[int] = []
        for key, value in mapping.items():
            if str(value).casefold() != low:
                continue
            try:
                uid = int(key)
            except (TypeError, ValueError):
                continue
            if uid not in out:
                out.append(uid)
        return sorted(out)

    @staticmethod
    def _memory_lookup_person_aliases(mapping, uid, name) -> list:
        if not isinstance(mapping, dict) or uid is None:
            return []
        value = mapping.get(str(uid), mapping.get(uid))
        if not value:
            return []
        value = str(value).strip()
        return [value] if value and value != name else []

    async def _memory_lookup_build(self, ctx, parsed: dict,
                                   person: dict) -> dict:
        """Purpose-роутинг (D3) — единая таблица без per-combination веток."""
        purpose = parsed["purpose"]
        max_items = parsed["max_items"]
        if person.get("resolution") == "ambiguous":
            return self._memory_lookup_payload(
                "ok", purpose, person, [], [], no_data=True,
                empty_reason="ambiguous")
        if not person.get("name") and person.get("user_id") is None:
            return self._memory_lookup_payload(
                "ok", purpose, person, [], [], no_data=True,
                empty_reason="unknown_person")
        handler = {
            "identity": self._memory_lookup_identity,
            "appearance": self._memory_lookup_appearance,
            "speech_style": self._memory_lookup_speech_style,
            "biography": self._memory_lookup_biography,
            "relationships": self._memory_lookup_relationships,
            "general": self._memory_lookup_general,
        }[purpose]
        return await handler(ctx, person, max_items)

    async def _memory_lookup_identity(self, ctx, person, max_items) -> dict:
        """identity: AliasResolver (name/aliases/id) + existing persona facts."""
        facts, sources = [], []
        db = getattr(self.deps, "db", None)
        reader = getattr(db, "get_user_context_facts", None)
        if callable(reader) and person.get("name"):
            rows = await reader(ctx.chat_id, person["name"], max_items,
                                int(time.time()))
            for row in rows or []:
                facts.append(self._memory_lookup_fact_item(row))
                sources.append(self._memory_lookup_source_item(row))
        if not facts:
            return self._memory_lookup_payload(
                "ok", "identity", person, [], [], no_data=True,
                empty_reason="unknown_person")
        return self._memory_lookup_payload(
            "ok", "identity", person, facts, sources,
            extra=self._memory_lookup_dossier_extra(facts))

    async def _memory_lookup_appearance(self, ctx, person, max_items) -> dict:
        """appearance: generic-фильтр поверх graph_facts + honest no_data.

        Извлечение/классификация внешности (в т.ч. из изображений) — A4 (U1);
        здесь только лексиконный отбор существующих подтверждённых фактов."""
        db = getattr(self.deps, "db", None)
        reader = getattr(db, "get_user_context_facts", None)
        if not callable(reader) or not person.get("name"):
            return self._memory_lookup_payload(
                "ok", "appearance", person, [], [], no_data=True,
                empty_reason="no_storage_for_purpose")
        rows = await reader(ctx.chat_id, person["name"],
                            _MEMORY_LOOKUP_APPEARANCE_SCAN, int(time.time()))
        facts, sources = [], []
        for row in rows or []:
            if not self._memory_lookup_is_appearance(str(row.get("fact") or "")):
                continue
            facts.append(self._memory_lookup_fact_item(row))
            sources.append(self._memory_lookup_source_item(row))
            if len(facts) >= max_items:
                break
        if not facts:
            return self._memory_lookup_payload(
                "ok", "appearance", person, [], [], no_data=True,
                empty_reason="no_storage_for_purpose")
        return self._memory_lookup_payload(
            "ok", "appearance", person, facts, sources)

    async def _memory_lookup_biography(self, ctx, person, max_items) -> dict:
        """biography: graph_facts (weight DESC) + generated слоя Б (portrait)."""
        facts, sources = [], []
        db = getattr(self.deps, "db", None)
        reader = getattr(db, "get_user_context_facts", None)
        if callable(reader) and person.get("name"):
            rows = await reader(ctx.chat_id, person["name"], max_items,
                                int(time.time()))
            for row in rows or []:
                facts.append(self._memory_lookup_fact_item(row))
                sources.append(self._memory_lookup_source_item(row))
        dossier = await self._memory_lookup_generated_dossier(db, ctx, person)
        if dossier:
            facts.append(self._memory_lookup_portrait_item(dossier))
            sources.append({
                "kind": "dossier_portrait", "ref": "dossier_portrait",
                "origin": "dossier_portrait",
                "ts": int(dossier.get("updated_at") or 0) or None})
        if not facts:
            return self._memory_lookup_payload(
                "ok", "biography", person, [], [], no_data=True,
                empty_reason="unknown_person")
        return self._memory_lookup_payload(
            "ok", "biography", person, facts, sources,
            extra=self._memory_lookup_dossier_extra(facts))

    async def _memory_lookup_relationships(self, ctx, person,
                                           max_items) -> dict:
        """relationships: edges из `db.get_persona_card.links` (D3)."""
        facts, sources = [], []
        db = getattr(self.deps, "db", None)
        getter = getattr(db, "get_persona_card", None)
        if callable(getter) and person.get("name"):
            card = await getter(ctx.chat_id, person["name"], max_items,
                                int(time.time()))
            for link in (card or {}).get("links") or []:
                source_name = str(link.get("source_name") or "").strip()
                target_name = str(link.get("target_name") or "").strip()
                relation = str(link.get("relation_type") or "").strip()
                if not source_name and not target_name:
                    continue
                facts.append({
                    "text": f"{source_name} ({relation}) {target_name}".strip(),
                    "confidence": "unknown", "weight": None, "time": None,
                    "source_id": ""})
                sources.append({"kind": "edge", "ref": "",
                                "origin": "graph_edge", "ts": None})
                if len(facts) >= max_items:
                    break
        if not facts:
            return self._memory_lookup_payload(
                "ok", "relationships", person, [], [], no_data=True,
                empty_reason="empty")
        return self._memory_lookup_payload(
            "ok", "relationships", person, facts, sources)

    async def _memory_lookup_general(self, ctx, person, max_items) -> dict:
        """general: lazy RAG — graph-факты + релевантные сообщения (D3)."""
        memory = getattr(self.deps, "memory", None)
        name = person.get("name") or ""
        message_cap = min(max_items, _MEMORY_LOOKUP_MESSAGE_SLICE_MAX,
                          _MEMORY_LOOKUP_MESSAGE_SLICE_HARD)
        facts, sources = [], []
        if memory is not None and hasattr(memory, "get_rag_facts"):
            try:
                rag = await memory.get_rag_facts(ctx.chat_id, name)
            except Exception:
                rag = []
            for entry in rag or []:
                built = self._memory_lookup_rag_fact_item(entry)
                if built is None:
                    continue
                facts.append(built["fact"])
                sources.append(built["source"])
                if len(facts) >= max_items:
                    break
        if (memory is not None and hasattr(memory, "search_long_term")
                and len(facts) < max_items):
            try:
                rows = await memory.search_long_term(
                    ctx.chat_id, keywords(name), limit=message_cap)
            except Exception:
                rows = []
            for row in rows or []:
                built = self._memory_lookup_message_item(row)
                if built is None:
                    continue
                facts.append(built["fact"])
                sources.append(built["source"])
                if len(facts) >= max_items:
                    break
        if not facts and memory is not None \
                and hasattr(memory, "get_rag_context"):
            try:
                text = await memory.get_rag_context(ctx.chat_id, name)
            except Exception:
                text = ""
            text = str(text or "").strip()
            if text:
                facts.append({
                    "text": _truncate(text, _MEMORY_LOOKUP_RAG_FACT_CHARS),
                    "confidence": "unknown", "weight": None, "time": None,
                    "source_id": "rag:context"})
                sources.append({"kind": "rag", "ref": "rag:context",
                                "origin": "rag", "ts": None})
        if not facts:
            return self._memory_lookup_payload(
                "ok", "general", person, [], [], no_data=True,
                empty_reason="empty")
        return self._memory_lookup_payload(
            "ok", "general", person, facts, sources)

    async def _memory_lookup_speech_style(self, ctx, person,
                                          max_items) -> dict:
        """speech_style: bounded per-user slice + patterns досье → compact
        профиль. Lazy RAG — только если срез не дал минимума характерных
        сообщений (D3). Системная личность бота НЕ меняется (стилизация —
        дело caller'а, §34)."""
        db = getattr(self.deps, "db", None)
        memory = getattr(self.deps, "memory", None)
        name = person.get("name") or ""
        uid = person.get("user_id")
        slice_cap = min(max_items, _MEMORY_LOOKUP_MESSAGE_SLICE_MAX,
                        _MEMORY_LOOKUP_MESSAGE_SLICE_HARD)
        facts, sources = [], []
        if db is not None and uid is not None \
                and hasattr(db, "get_recent_messages"):
            rows = await db.get_recent_messages(ctx.chat_id,
                                                _MEMORY_LOOKUP_STYLE_SCAN)
            user_msgs = []
            for row in rows or []:
                item = dict(row)
                if int(item.get("user_id") or 0) != int(uid):
                    continue
                if not str(item.get("text") or "").strip():
                    continue
                user_msgs.append(item)
            for item in user_msgs[-slice_cap:]:
                built = self._memory_lookup_message_item(item)
                if built is not None:
                    facts.append(built["fact"])
                    sources.append(built["source"])
        if len(facts) < _MEMORY_LOOKUP_STYLE_MIN_MESSAGES \
                and memory is not None \
                and hasattr(memory, "search_long_term"):
            try:
                rows = await memory.search_long_term(
                    ctx.chat_id, keywords(name), limit=slice_cap)
            except Exception:
                rows = []
            for row in rows or []:
                if uid is not None:
                    item = dict(row)
                    if int(item.get("user_id") or 0) != int(uid):
                        continue
                    row = item
                built = self._memory_lookup_message_item(row)
                if built is not None:
                    facts.append(built["fact"])
                    sources.append(built["source"])
                    if len(facts) >= slice_cap:
                        break
        dossier = await self._memory_lookup_generated_dossier(db, ctx, person)
        if dossier:
            patterns = [str(x).strip() for x in (dossier.get("patterns") or [])
                        if str(x).strip()]
            themes = [str(x).strip() for x in (dossier.get("themes") or [])
                      if str(x).strip()]
            profile = self._memory_lookup_style_profile(patterns, themes)
            if profile:
                ts = int(dossier.get("updated_at") or 0) or None
                facts.append({"text": profile, "confidence": "unknown",
                              "weight": None, "time": ts,
                              "source_id": "dossier_portrait"})
                sources.append({"kind": "profile", "ref": "dossier_patterns",
                                "origin": "dossier_portrait", "ts": ts})
        if not facts:
            return self._memory_lookup_payload(
                "ok", "speech_style", person, [], [], no_data=True,
                empty_reason="empty")
        return self._memory_lookup_payload(
            "ok", "speech_style", person, facts, sources)

    async def _memory_lookup_generated_dossier(self, db, ctx, person):
        """Reuse `db.get_generated_dossier` (Слой Б) — fail-open → None."""
        getter = getattr(db, "get_generated_dossier", None)
        name = person.get("name")
        if not callable(getter) or not name:
            return None
        try:
            return await getter(ctx.chat_id, name)
        except Exception:
            logger.warning("[tools] memory lookup dossier read failed | "
                           "chat=%s", getattr(ctx, "chat_id", None))
            return None

    def _memory_lookup_fact_item(self, row: dict) -> dict:
        """graph_facts-строка → факт envelope (per-fact confidence/source)."""
        weight = row.get("weight")
        return {
            "text": str(row.get("fact") or "").strip(),
            "confidence": self._memory_lookup_conf_label(
                str(row.get("status") or ""), weight),
            "weight": float(weight) if weight is not None else None,
            "time": int(row.get("message_timestamp")
                        or row.get("created_at") or 0) or None,
            "source_id": resolve_item_id(
                tg_message_id=row.get("tg_message_id"), fact_id=row.get("id")),
        }

    def _memory_lookup_source_item(self, row: dict) -> dict:
        return {
            "kind": "graph_fact",
            "ref": resolve_item_id(tg_message_id=row.get("tg_message_id"),
                                   fact_id=row.get("id")),
            "origin": str(row.get("origin") or ""),
            "ts": int(row.get("message_timestamp")
                      or row.get("created_at") or 0) or None,
        }

    def _memory_lookup_rag_fact_item(self, entry):
        """RAG-факт (4-кортеж origin/fact/ts/target или dict) → fact+source."""
        if isinstance(entry, dict):
            origin = str(entry.get("origin") or "")
            text = str(entry.get("fact") or entry.get("text") or "").strip()
            ts = int(entry.get("rag_ts") or entry.get("message_timestamp")
                     or entry.get("created_at") or 0) or None
        elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
            origin = str(entry[0] or "")
            text = str(entry[1] or "").strip()
            ts = (int(entry[2] or 0) or None) if len(entry) > 2 else None
        else:
            return None
        if not text:
            return None
        fact = {"text": _truncate(text, _MEMORY_LOOKUP_RAG_FACT_CHARS),
                "confidence": "unknown", "weight": None, "time": ts,
                "source_id": ""}
        source = {"kind": "rag", "ref": "", "origin": origin or "rag",
                  "ts": ts}
        return {"fact": fact, "source": source}

    def _memory_lookup_message_item(self, row):
        """smart_messages-строка → короткий факт (slice ≤240) + msg/tg-источник."""
        try:
            item = dict(row)
        except (TypeError, ValueError):
            return None
        text = str(item.get("text") or "").strip()
        if not text:
            return None
        ts = int(item.get("timestamp") or 0) or None
        ref = resolve_item_id(tg_message_id=item.get("tg_message_id"),
                              message_id=item.get("id"))
        fact = {"text": _truncate(text, _MEMORY_LOOKUP_SLICE_MAX_CHARS),
                "confidence": "unknown", "weight": None, "time": ts,
                "source_id": ref}
        source = {"kind": "message", "ref": ref, "origin": "chat_history",
                  "ts": ts}
        return {"fact": fact, "source": source}

    @staticmethod
    def _memory_lookup_dossier_extra(facts) -> dict:
        """Reuse `format_dossier_block` для компактного рендера фактов."""
        try:
            from services.dossier_prompts import format_dossier_block
            texts = [str(f.get("text") or "") for f in facts
                     if str(f.get("text") or "").strip()]
            block = format_dossier_block(texts, [],
                                         _MEMORY_LOOKUP_RESULT_MAX_CHARS)
        except Exception:
            block = ""
        return {"dossier": block} if block else {}

    @staticmethod
    def _memory_lookup_portrait_item(dossier: dict) -> dict:
        text = str(dossier.get("portrait") or "").strip()
        if not text:
            patterns = [str(x).strip() for x in (dossier.get("patterns") or [])
                        if str(x).strip()]
            themes = [str(x).strip() for x in (dossier.get("themes") or [])
                      if str(x).strip()]
            parts = []
            if patterns:
                parts.append("Паттерны: " + "; ".join(patterns))
            if themes:
                parts.append("Темы: " + "; ".join(themes))
            text = " ".join(parts)
        return {"text": text[:_MEMORY_LOOKUP_PORTRAIT_MAX_CHARS],
                "confidence": "unknown", "weight": None,
                "time": int(dossier.get("updated_at") or 0) or None,
                "source_id": "dossier_portrait"}

    @staticmethod
    def _memory_lookup_style_profile(patterns, themes) -> str:
        parts = []
        if patterns:
            parts.append("Паттерны речи: " + "; ".join(patterns[:5]))
        if themes:
            parts.append("Темы: " + "; ".join(themes[:5]))
        return _truncate(" ".join(parts), _MEMORY_LOOKUP_PORTRAIT_MAX_CHARS)

    @staticmethod
    def _memory_lookup_conf_label(status, weight) -> str:
        """graph_facts.status+weight → confirmed/likely/unconfirmed (D4)."""
        if str(status or "").strip().lower() != "confirmed":
            return "unconfirmed"
        try:
            value = float(weight) if weight is not None else None
        except (TypeError, ValueError):
            value = None
        if value is None or value >= _MEMORY_LOOKUP_CONFIRMED_WEIGHT:
            return "confirmed"
        return "likely"

    @staticmethod
    def _memory_lookup_is_appearance(text: str) -> bool:
        low = str(text or "").casefold()
        return any(stem in low for stem in _APPEARANCE_LEXICON)

    @staticmethod
    def _memory_lookup_person_dict(person: dict) -> dict:
        out = {
            "name": str(person.get("name") or ""),
            "user_id": person.get("user_id"),
            "resolution": str(person.get("resolution") or "resolved"),
        }
        aliases = list(person.get("aliases") or [])
        if aliases:
            out["aliases"] = aliases
        if out["resolution"] == "ambiguous":
            out["candidates"] = list(person.get("candidates") or [])
        return out

    @staticmethod
    def _memory_lookup_confidence(facts) -> dict:
        """Агрегат подтверждённости (D4): нет носителя → available=false/unknown;
        ни один элемент не помечен confirmed без подтверждения носителем."""
        labels = [str(f.get("confidence") or "unknown") for f in facts or []]
        weights = [float(f.get("weight")) for f in facts or []
                   if f.get("weight") is not None]
        if not labels or all(lbl == "unknown" for lbl in labels):
            return {"available": False, "label": "unknown", "value": None}
        if "confirmed" in labels:
            label = "confirmed"
        elif "likely" in labels:
            label = "likely"
        else:
            label = "unconfirmed"
        return {"available": True, "label": label,
                "value": max(weights) if weights else None}

    @staticmethod
    def _memory_lookup_time_context(facts) -> dict:
        times = [int(f.get("time")) for f in facts or [] if f.get("time")]
        if not times:
            return {"from": None, "to": None, "label": ""}
        lo, hi = min(times), max(times)
        try:
            y_lo = datetime.datetime.fromtimestamp(lo).year
            y_hi = datetime.datetime.fromtimestamp(hi).year
        except (ValueError, OSError, OverflowError):
            return {"from": lo, "to": hi, "label": ""}
        label = str(y_lo) if y_lo == y_hi else f"{y_lo}–{y_hi}"
        return {"from": lo, "to": hi, "label": label}

    def _memory_lookup_payload(self, status, purpose, person, facts, sources,
                               *, no_data=False, empty_reason="",
                               extra=None) -> dict:
        """Envelope из 5 полей §33 (D4) + служебные (status/purpose/person/
        no_data/empty_reason/truncated)."""
        facts = list(facts or [])[:_MEMORY_LOOKUP_MAX_ITEMS_HARD]
        sources = list(sources or [])[:_MEMORY_LOOKUP_MAX_ITEMS_HARD]
        is_empty = bool(no_data) or not facts
        payload = {
            "status": status,
            "purpose": purpose,
            "person": self._memory_lookup_person_dict(person),
            "facts": facts,
            "sources": sources,
            "confidence": self._memory_lookup_confidence(facts),
            "time_context": self._memory_lookup_time_context(facts),
            "no_data": is_empty,
            "empty_reason": (empty_reason if is_empty else ""),
            "truncated": False,
        }
        if extra:
            payload.update(extra)
        return payload

    def _resolve_tool_source(self, arguments: dict, ctx: ToolContext,
                             kinds: tuple[str, ...] | None = None):
        """Общий резолв источника медиа-инструментов (F14, §4.5):

        * ``source == "reply"`` → нативный путь при доступном видео (приоритет
          над http-``url`` — спецификация §4.5); иначе нет источника;
        * http(s)-``url`` → ``("link", url, None)``;
        * иначе при нативном медиа в ``ctx.native_media`` (по умолчанию
          video/видео-document) → ``("native", None, media)``;
        * иначе ``(None, None, None)``.

        ``kinds`` — какие виды нативного медиа допустимы: по умолчанию
        ``native_media.VIDEO_KINDS`` (F14, video/document); F19
        ``transcribe_video`` передаёт ``native_media.MEDIA_KINDS``
        (включая voice/video_note). Kill-switch ``NATIVE_MEDIA_TOOLS_ENABLED``
        OFF → нативный резолв не срабатывает (прежнее поведение: нужен
        http-``url``)."""
        allowed = kinds if kinds is not None else native_media.VIDEO_KINDS
        args = arguments if isinstance(arguments, dict) else {}
        url = str(args.get("url") or "").strip()
        source = str(args.get("source") or "").strip().lower()
        native = getattr(ctx, "native_media", None)
        native_ok = (native is not None
                     and getattr(native, "kind", "") in allowed)
        if source == "reply":
            if _native_tools_enabled() and native_ok:
                return "native", None, native
            return None, None, None
        if _is_http_url(url):
            return "link", url, None
        if _native_tools_enabled() and native_ok:
            return "native", None, native
        return None, None, None

    def _download_cooldown(self):
        """Общий download-кулдаун роутера 4e | None (R10.15-9). Провайдер —
        zero-arg callable (ленивая ссылка на трекер); сбой провайдера → None
        (не роняем tool-loop)."""
        provider = getattr(self.deps, "download_cooldown", None)
        if provider is None:
            return None
        try:
            return provider() if callable(provider) else provider
        except Exception:
            logger.warning("[tools] download cooldown unavailable")
            return None

    async def _download_media(self, arguments: dict, ctx: ToolContext) -> str:
        """Корнер-кейс файлов (ADR-1015-3 §4) + запрос качества (ADR-1017-2).

        Раунд 10.17 (F2, ADR-1017-2 §2 — SUPERSEDE ADR-1016-1 §2 п.3/§3):
        платформенный URL → `probe()` → инлайн-меню качества `tdq:<height>` →
        фиктивный `tool_response {"status":"needs_quality"}`; скачивание
        доводит callback `tdq:` (роутер 4e). Прямой медиа-URL или ЯВНО
        названное пользователем `quality` → скачиваем сразу без меню. Провал
        probe → одна bounded попытка `download(url, None)` без меню.

        Файл шлём САМИ (send_media), в LLM — фиктивный JSON (модель не
        «печатает» видео). Кулдаун (D279) жжётся только после успешного probe
        (ask-ветка) либо успешного download. R17: без URL/текстов в логах."""
        source, url, native = self._resolve_tool_source(arguments, ctx)
        if source is None:
            return _download_status("error", "Некорректная ссылка")
        if not hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):
            return _download_status("error", "Скачивание отключено")
        if ctx.bot is None:
            return _download_status("error", "Скачивание недоступно")
        # (а) нативный источник (F14): пересылка TG-файла без меню качества и
        # без download-кулдауна (паритет Fast-Track `_handle_native_media`).
        if source == "native":
            return await self._download_native(ctx, native)
        if self.deps.downloader is None:
            return _download_status("error", "Скачивание недоступно")
        # Follow-up R10.15-9: уважаем общий download-кулдаун роутера 4e
        # (тот же трекер через DI-провайдер; R17 — без URL/текстов в логах).
        cooldown = self._download_cooldown()
        if cooldown is not None and ctx.user_id is not None:
            cooldown_refresh(cooldown, hot.get("limits.download_cooldown",
                                               settings.DOWNLOAD_COOLDOWN))
            remaining = await cooldown_remaining(cooldown, ctx.chat_id,
                                                 ctx.user_id)
            if remaining > 0:
                return _download_status("error",
                                        "Скачивание на кулдауне — позже")

        # (а) явное качество ИЛИ прямой медиа-URL → без меню (ADR-1017-2 §2.3/§2.2).
        explicit = self._quality_arg(arguments.get("quality"))
        if explicit is not None or is_direct_media_url(url):
            return await self._download_now(ctx, url, explicit, cooldown)

        # (б) платформа → probe → меню качества (эталон Fast-Track :284-343).
        try:
            probe = await asyncio.wait_for(self.deps.downloader.probe(url),
                                           timeout=_PROBE_TOOL_TIMEOUT)
        except DownloadError as exc:
            # R17: только класс + safe-reason, БЕЗ str(exc) (может нести URL).
            logger.warning(
                "[tools] download probe failed | tool=download_media | "
                "error=%s reason=%s", type(exc).__name__, exc.reason)
            return await self._download_now(ctx, url, None, cooldown)
        except Exception as exc:
            logger.warning(
                "[tools] download probe failed | tool=download_media | "
                "error=%s", type(exc).__name__)
            # (в) bounded fallback: одна попытка без меню (ADR-1017-2 §2.4).
            return await self._download_now(ctx, url, None, cooldown)

        # D279: touch только после успешного probe (fail кулдаун не жжёт).
        # Ревью-итер.1 L5: touch — ПОСЛЕ успешной отправки меню, чтобы провал
        # доставки не оставлял пользователя без меню, но с кулдауном.
        title = getattr(probe, "title", None)
        qualities = getattr(probe, "qualities", ()) or ()
        store_tool_download_pending(
            ctx.chat_id, ctx.user_id, url=url, title=title,
            qualities=qualities, trigger_message_id=ctx.reply_to_message_id)
        try:
            await self._send_quality_menu(ctx, title, qualities)
        except Exception as exc:
            logger.warning(
                "[tools] quality menu send failed | tool=download_media | "
                "error=%s", type(exc).__name__)
            _TOOL_DL_PENDING.pop((ctx.chat_id, ctx.user_id), None)
            return _download_status("error", "Не удалось отправить меню качества")
        if cooldown is not None and ctx.user_id is not None:
            await cooldown_touch(cooldown, ctx.chat_id, ctx.user_id)
        return _download_status(
            "needs_quality",
            "Пользователю предложен выбор качества — меню с кнопками "
            "отправлено в чат")

    async def _download_native(self, ctx: ToolContext, native) -> str:
        """Нативная пересылка TG-файла (F14, ADR-1024-15 §2.1/§2.3):
        `fetch_media_to_tmp` → `send_media`; меню качества НЕ предлагается,
        download-кулдаун НЕ жжётся; лимит 2 ГБ (лимит Telegram). tmp чистится в
        finally. R17: без file_id/URL/локальных путей в логах."""
        path = None
        try:
            path = await asyncio.wait_for(
                native_media.download_to_tmp(
                    ctx.bot, native, timeout=_DOWNLOAD_TOOL_TIMEOUT),
                timeout=_DOWNLOAD_TOOL_TIMEOUT)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size > _DOWNLOAD_NATIVE_MAX_BYTES:
                logger.warning(
                    "[tools] native download too big | tool=download_media | "
                    "bytes=%d", size)
                return _download_status("error",
                                        "Файл больше лимита Telegram")
            await send_media(ctx.bot, ctx.chat_id, path,
                             reply_to=ctx.reply_to_message_id)
        except asyncio.TimeoutError:
            logger.warning(
                "[tools] native download timeout | tool=download_media")
            return _download_status("error", "Таймаут нативного скачивания")
        except Exception as exc:
            logger.warning(
                "[tools] native download failed | tool=download_media | "
                "error=%s", type(exc).__name__)
            return _download_status("error", "Не удалось переслать видео")
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        return _download_status("success", "Файл успешно загружен в чат")

    async def _download_now(self, ctx: ToolContext, url: str, quality,
                            cooldown) -> str:
        """Скачать и отправить без меню (direct / явное качество / fallback).

        Успех — только после реальной отправки файла; провал download или
        send → честный `status:"error"` (без URL в логах, R17)."""
        path = None
        try:
            path = await asyncio.wait_for(
                self.deps.downloader.download(url, quality),
                timeout=_DOWNLOAD_TOOL_TIMEOUT)
        except DownloadError as exc:
            logger.warning(
                "[tools] download failed | tool=download_media | "
                "error=%s reason=%s", type(exc).__name__, exc.reason)
            return _download_status("error", "Не удалось скачать видео")
        except Exception as exc:
            logger.warning(
                "[tools] download failed | tool=download_media | error=%s",
                type(exc).__name__)
            return _download_status("error", "Не удалось скачать видео")
        if cooldown is not None and ctx.user_id is not None:
            # D279: успешный download жжёт кулдаун (провал — нет).
            await cooldown_touch(cooldown, ctx.chat_id, ctx.user_id)
        try:
            await send_media(ctx.bot, ctx.chat_id, path,
                             reply_to=ctx.reply_to_message_id)
        except Exception as exc:
            logger.warning(
                "[tools] media send failed | tool=download_media | error=%s",
                type(exc).__name__)
            return _download_status("error", "Не удалось отправить файл")
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return _download_status("success", "Файл успешно загружен в чат")

    def _quality_arg(self, raw):
        """enum-значение `quality` из аргументов → нормализованный `"max"`/`"1080"`.

        Мусор/пусто → None (не роняем: тогда работает меню). Нормализация —
        тот же `_normalize_quality` downloader'а, что и Fast-Track (T-1679)."""
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return self.deps.downloader._normalize_quality(raw)
        except DownloadError:
            return None
        except Exception:
            logger.warning("[tools] invalid quality arg | tool=download_media")
            return None

    async def _send_quality_menu(self, ctx: ToolContext, title,
                                 qualities) -> None:
        """Инлайн-меню качества tool-пути `tdq:<height>` — единый хелпер
        `services.media_send.send_quality_menu` (T-1679; без дублирования меню
        с Fast-Track). R17: в лог — только chat_id и число качеств."""
        await send_quality_menu(
            ctx.bot, ctx.chat_id, reply_to=ctx.reply_to_message_id, title=title,
            qualities=qualities, callback_prefix=_TOOL_QUALITY_PREFIX)
        logger.info("[tools] download quality menu sent | chat=%s | qualities=%d",
                    ctx.chat_id, len(qualities))

    async def _get_bot_health(self, arguments: dict, ctx: ToolContext) -> str:
        """Здоровье бота: тот же путь, что роутер 0g — CheckupLogsFetcher.fetch
        → CheckupService.checkup. Кулдаун не применяем (вызов по интенту LLM;
        ограничение — лимиты tool-loop). R17: без текстов логов.

        Follow-up R10.15-2: уважаем master-флаг модуля (`flags.checkup_enabled`,
        тот же гейт, что `handlers/checkup.py`) — при выключенном модуле
        инструмент не делает сетевой/LLM-вызов, а возвращает честную ошибку."""
        if not hot.get("flags.checkup_enabled", settings.CHECKUP_ENABLED):
            return "ОШИБКА get_bot_health: модуль выключен"
        health = self.deps.health
        if health is None or getattr(health, "service", None) is None \
                or getattr(health, "fetcher", None) is None:
            return "ОШИБКА get_bot_health: сервис недоступен"
        try:
            logs, used_fallback = await health.fetcher.fetch()
            report = await health.service.checkup(logs, used_fallback)
        except Exception as exc:
            logger.warning("[tools] get_bot_health failed | error=%s",
                           type(exc).__name__)
            return f"ОШИБКА get_bot_health: {type(exc).__name__}"
        text = str(report or "").strip()
        if not text:
            return "ОШИБКА get_bot_health: пустой отчёт"
        return _truncate(text, _MEMORY_MAX_SYMBOLS)

    async def _get_recent_history(self, arguments: dict,
                                  ctx: ToolContext) -> str:
        """F9 (spec §2-§5): сырая хронологическая стенограмма недавних
        сообщений чата («Имя: текст») — кратковременная память, НЕ RAG.

        Путь A (`depth`): `database.get_recent_messages(chat_id, depth)` —
        последние N сообщений в хронологическом порядке (ASC).
        Путь B (`query`): FTS по L1 + пост-фильтр окна _HISTORY_QUERY_WINDOW_
        SECONDS + сортировка ASC. Приоритет — `query`; если параметров нет —
        `depth = _HISTORY_DEFAULT_DEPTH`.

        НЕ бросает: ошибка/пусто/сбой → структурная строка (R17: в логах
        только chat_id/count/out_chars, без текстов/URL/имён)."""
        args = arguments if isinstance(arguments, dict) else {}
        query = str(args.get("query") or "").strip()
        depth = _history_depth(args.get("depth"))
        # Follow-up R10.15-6 (spec F9 §5): модель не передала ни query, ни
        # depth, но есть свободный текст сообщения → используем его как query.
        # Явный depth НЕ перекрывается (depth-путь сохранён).
        if not query and args.get("depth") in (None, ""):
            query = str(getattr(ctx, "query", "") or "").strip()
        db = self.deps.db if self.deps.db is not None \
            else getattr(self.deps.memory, "db", None)
        try:
            if query:
                lines = await asyncio.wait_for(
                    self._recent_history_by_query(ctx, query),
                    timeout=_HISTORY_TOOL_TIMEOUT)
            else:
                lines = await asyncio.wait_for(
                    self._recent_history_by_depth(ctx, db, depth),
                    timeout=_HISTORY_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] get_recent_history timeout | chat=%s",
                           ctx.chat_id)
            return "ОШИБКА get_recent_history: timeout"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[tools] get_recent_history failed | chat=%s | error=%s",
                ctx.chat_id, type(exc).__name__)
            return f"ОШИБКА get_recent_history: {type(exc).__name__}"
        if not lines:
            logger.info("[tools] get_recent_history | chat=%s | count=0 | "
                        "out_chars=0", ctx.chat_id)
            return _HISTORY_EMPTY
        text = _truncate("\n".join(lines), _HISTORY_MAX_SYMBOLS)
        logger.info("[tools] get_recent_history | chat=%s | count=%d | "
                    "out_chars=%d", ctx.chat_id, len(lines), len(text))
        return text

    async def _recent_history_by_depth(self, ctx: ToolContext, db, depth: int
                                       ) -> list[str]:
        """Путь A: последние `depth` сообщений чата (ASC). DDL не нужен —
        переиспользуем read-API `database.get_recent_messages`."""
        if db is None or not hasattr(db, "get_recent_messages"):
            raise RuntimeError("db недоступен")
        rows = await db.get_recent_messages(ctx.chat_id, depth)
        return self._history_lines(rows)

    async def _recent_history_by_query(self, ctx: ToolContext, query: str
                                       ) -> list[str]:
        """Путь B: FTS по L1 + фильтр окна последних часов → ASC-стенограмма."""
        since = int(time.time()) - _HISTORY_QUERY_WINDOW_SECONDS
        rows = await self.deps.memory.search_long_term(
            ctx.chat_id, keywords(query), limit=_HISTORY_SEARCH_LIMIT)
        # T-678: aiosqlite.Row не имеет .get → нормализация в dict.
        rows = [dict(row) for row in rows]
        rows = [r for r in rows if int(r.get("timestamp") or 0) >= since]
        rows.sort(key=lambda r: int(r.get("timestamp") or 0))
        return self._history_lines(rows)

    def _history_lines(self, rows) -> list[str]:
        """Строки smart_messages → канонические строки контекста (10.20,
        БЛОК 0, ADR-1020-1 ред. 3, точка 8): «[ts | Имя | ID | Переслано]:
        текст» (R16-каскад имён; пустой текст без медиа пропускается;
        медиа-событие — маркером)."""
        lines: list[str] = []
        for row in rows or []:
            try:
                item = dict(row)
            except (TypeError, ValueError):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                media = str(item.get("media_type") or "").strip()
                if not media or media == "text":
                    continue
                text = f"[медиа: {media}]"
            forward_source = (item.get("forward_source")
                              if item.get("is_forward") else None)
            lines.append(format_context_item(
                ts=item.get("timestamp"), author=self._resolve_name(item),
                item_id=resolve_item_id(
                    tg_message_id=item.get("tg_message_id"),
                    message_id=item.get("id")),
                forward_source=forward_source, text=text, kind="msg"))
        return lines

    # ── compile_lore_story (раунд 10.20, БЛОК 1, ADR-1020-4 п.1-4, T-1887) ──

    async def _chat_timezone(self, chat_id: int | None) -> str:
        """S10.20-14: tz чата (per-chat override → hot → код-дефолт) для
        рендера дат Летописца; пусто → фолбэк `limits.summary_timezone`
        (существующая tz-инфраструктура, расписания не трогаем). Возвращает
        ВАЛИДНОЕ имя tz (неизвестное → UTC)."""
        from services.canonical_context import resolve_timezone
        fallback = hot.get("limits.summary_timezone",
                           getattr(settings, "SUMMARY_TIMEZONE", ""))
        global_tz = hot.get("limits.chat_timezone",
                            getattr(settings, "CHAT_TIMEZONE", ""))
        tz = global_tz
        if chat_id is not None:
            try:
                from services.chat_params import get_chat_param
                tz = await get_chat_param(chat_id, "limits.chat_timezone",
                                          global_tz)
            except Exception:
                logger.warning("[tools] chat tz resolve failed — global | "
                               "chat=%s", chat_id)
                tz = global_tz
        return resolve_timezone(tz, fallback=str(fallback or "UTC"))


    async def _compile_lore_story(self, arguments: dict,
                                  ctx: ToolContext) -> str:
        """«Летописец»: Шаг А (граф) + Шаг Б (хронология) → JSON-контракт →
        изолированный синтез своим каноном `LORE_STORY_SYSTEM_PROMPT`
        (LoreCompilerService) → готовый рассказ. При успехе ставит
        ``ctx.lore_compiled = True`` (сигнал доставки, ADR-1020-6 п.2).

        Гейт: ``flags.lore_compiler_enabled`` (О3, default ON) — OFF → честная
        строка отключения, LLM не вызывается. НЕ бросает: таймаут/сбой →
        «ОШИБКА …» (диалог не роняется, NFR-4). R17: без текстов истории."""
        if not await resolve_lore_compiler_flag(ctx.chat_id):
            return "Инструмент compile_lore_story отключен."
        topic = self._require_str(arguments, "topic") or str(ctx.query or "")
        topic = topic.strip()
        if not topic:
            return "ОШИБКА compile_lore_story: не указан topic"
        db = self.deps.db if self.deps.db is not None \
            else getattr(self.deps.memory, "db", None)
        if db is None or self.deps.llm is None:
            return "ОШИБКА compile_lore_story: сервис недоступен"
        try:
            from services.lore_compiler_service import LoreCompilerService
            tz_name = await self._chat_timezone(ctx.chat_id)
            service = LoreCompilerService(db, self.deps.llm, self.deps.aliases,
                                          tz_name=tz_name)
            result = await asyncio.wait_for(
                service.compile(ctx.chat_id, topic), timeout=_LORE_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] compile_lore_story timeout | chat=%s",
                           ctx.chat_id)
            return "ОШИБКА compile_lore_story: timeout"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[tools] compile_lore_story failed | chat=%s | "
                           "error=%s", ctx.chat_id, type(exc).__name__)
            return f"ОШИБКА compile_lore_story: {type(exc).__name__}"
        status = str(result.get("status") or "")
        if status != "ok":
            return str(result.get("message")
                       or "ОШИБКА compile_lore_story: не удалось собрать историю")
        story = str(result.get("story") or "").strip()
        if not story:
            return "ОШИБКА compile_lore_story: пустая история"
        ctx.lore_compiled = True
        ctx.lore_story = story
        payload = json.dumps({
            "status": "ok",
            "is_update": bool(result.get("is_update")),
            "previous_story_at": result.get("previous_story_at"),
            "story": story,
        }, ensure_ascii=False)
        if getattr(ctx, "lore_verbatim_instruction", True):
            return f"{payload}\n\n{_LORE_RETURN_INSTRUCTION}"
        return payload

    async def _generate_image(self, arguments: dict, ctx: ToolContext) -> str:
        """Раунд 10.23 (F5, ADR-1023-5): генерация изображения по промпту.

        Бэкенд САМ отправляет изображение в чат (`services.image_generation`),
        модели возвращается короткий JSON-статус (прецедент `download_media`).
        Гейт модуля: env-рубильник + каталоговый тумблер (per-chat). Провал
        провайдера/бюджета → циничная отмазка в статусе, бот жив. R17: без
        промпта/URL/ключа в логах.

        A3 (§21/ADR-1026-16 D3/D2/D4): (1) ПЕРВЫМ делом проверяется
        авторитетный маркер прогона ``ctx.image_request_handled`` — True →
        ``{"status":"skipped","reason":"already_handled"}`` без генерации/
        списания бюджета (двойная генерация исключена); гейтился киль-свитчем
        ``UNIFIED_IMAGE_REQUEST_ENABLED``; (2) запрос строится как единый
        ``ImageRequest`` (source="tool") → единый раннер → существующий
        ``generate_and_send``; OFF — прежний прямой вызов; (3) валидация
        аргументов fail-closed (статус `error` НЕ роняет цикл, FAIL-closed
        исключений нет); (4) реальный `reason` генератора доводится —
        вымышленный «отказ модели» не подставляется."""
        # D3, слой 2: маркер прогона — до любого гейта модуля/генерации.
        if image_generation.unified_image_request_enabled() \
                and getattr(ctx, "image_request_handled", False):
            logger.info("[tools] generate_image skipped | reason="
                        "already_handled | chat=%s", ctx.chat_id)
            return json.dumps(
                {"status": "skipped", "reason": "already_handled",
                 "message": "Изображение на этом ходу уже обработано "
                            "(генерация выполняется один раз)"},
                ensure_ascii=False)
        if not await image_generation.resolve_module_enabled(ctx.chat_id):
            return json.dumps({"status": "error",
                               "message": "Генерация изображений отключена"},
                              ensure_ascii=False)
        prompt = self._require_str(arguments, "prompt")
        if not prompt:
            return json.dumps({"status": "error",
                               "message": "Не указан prompt"},
                              ensure_ascii=False)
        if image_generation.unified_image_request_enabled():
            request = image_generation.build_image_request(
                "tool", ctx.chat_id, prompt,
                requester_id=getattr(ctx, "user_id", None),
                original_message_id=getattr(ctx, "reply_to_message_id", None))
            # A4 (ADR-1026-19 D1/D2/§7.3): тот же helper, что у direct-пути;
            # память читается только при ON kill-switch и разрешённом субъекте.
            if image_generation.image_context_memory_enabled():
                deps = getattr(self, "deps", None)
                data = await image_context_memory.build_image_memory_context(
                    chat_id=ctx.chat_id, user_request=prompt,
                    requester_id=getattr(ctx, "user_id", None),
                    aliases=getattr(deps, "aliases", None),
                    db=getattr(deps, "db", None),
                    memory=getattr(deps, "memory", None))
                image_context_memory.attach_image_memory(request, data)
            result = await image_generation.run_image_request(
                request, bot=ctx.bot,
                correlation_id=getattr(ctx, "correlation_id", None))
        else:
            # A5 (ADR-1026-17 D3): source="tool" — idem-дискриминатор
            # входа (резерв/журнал); генератор и контракт прежние.
            request = None
            result = await image_generation.generate_and_send(
                ctx.bot, ctx.chat_id, prompt,
                reply_to_message_id=ctx.reply_to_message_id,
                correlation_id=getattr(ctx, "correlation_id", None),
                source="tool")
        if result.ok:
            payload = {"status": "success",
                       "message": "Изображение сгенерировано и отправлено в чат"}
            note = _image_memory_note(request)
            if note:
                payload["note"] = note
            return json.dumps(payload, ensure_ascii=False)
        logger.info("[tools] generate_image failed | chat=%s | reason=%s",
                    ctx.chat_id, result.reason)
        return json.dumps(
            {"status": "error", "reason": result.reason,
             "message": image_generation.IMAGE_GENERATION_FALLBACK_PHRASE},
            ensure_ascii=False)

    # ── helpers dig (T-820; переиспользуют _require_query/_resolve_name) ──
    @staticmethod
    def _dig_year(raw) -> int | None:
        """year-параметр → int (вне [2000, текущий] → None; кривой тип →
        None). Период «N лет назад» парсится отдельно — _dig_year_from_query."""
        if raw in (None, ""):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        if value < _DIG_YEAR_MIN or value > datetime.datetime.now().year:
            return None
        return value

    @classmethod
    def _dig_year_from_query(cls, query: str) -> int | None:
        """Фикс-раунд (major-2): «N лет назад» в тексте запроса при year
        None → год = текущий − N (N 1..50); слова «несколько/пару/тройку
        лет назад» → 3/2/3. Вне диапазона [2000, текущий] → None."""
        text = str(query or "").casefold()
        n = None
        m = _DIG_YEARS_AGO_NUM_RE.search(text)
        if m:
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                n = None
        else:
            m = _DIG_YEARS_AGO_WORD_RE.search(text)
            if m:
                n = _DIG_YEARS_AGO_WORDS.get(m.group(1))
        if not n or n < 1 or n > 50:
            return None
        year = datetime.datetime.now().year - n
        if year < _DIG_YEAR_MIN:
            return None
        return year

    async def _dig_graph_names(self, ctx: ToolContext,
                               seed_terms: list[str]) -> list[str]:
        """major-2(б)/spec п.4: имена из графа для FTS-расширения: BFS по
        nodes/edges (db.dig_graph_related_names, глубина limits.
        dig_graph_hop_depth); если узлы/рёбра пусты или недоступны — фолбэк
        db.dig_fallback_target_names (target_user фактов, содержащие токен).
        Best-effort: любая ошибка/нет db/нет токенов → [] (WARNING)."""
        db = getattr(self.deps.memory, "db", None)
        seeds = [str(t).strip() for t in (seed_terms or [])
                 if len(str(t).strip()) >= 4]
        if db is None or not seeds:
            return []
        depth = int(hot.get("limits.dig_graph_hop_depth",
                            settings.DIG_GRAPH_HOP_DEPTH)
                    or settings.DIG_GRAPH_HOP_DEPTH)
        depth = min(max(1, depth), _DIG_GRAPH_MAX_HOP_DEPTH)
        try:
            if hasattr(db, "dig_graph_related_names"):
                names = await db.dig_graph_related_names(
                    ctx.chat_id, seeds, max_depth=depth)
                if names:
                    return names
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[tools] dig graph names failed — fallback target_user | "
                "chat=%s", ctx.chat_id, exc_info=True)
        try:
            if hasattr(db, "dig_fallback_target_names"):
                return await db.dig_fallback_target_names(
                    ctx.chat_id, seeds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[tools] dig fallback target_user failed — empty | "
                "chat=%s", ctx.chat_id, exc_info=True)
        return []

    @staticmethod
    def _year_bounds(year: int) -> tuple[int, int] | None:
        """[Y-01-01 00:00, Y-12-31 23:59:59] local — unix-диапазон для
        пост-фильтра по timestamp (spec §3.2.1 п.3(а))."""
        if not year:
            return None
        start = datetime.datetime(year, 1, 1, 0, 0).timestamp()
        end = datetime.datetime(year, 12, 31, 23, 59, 59).timestamp()
        return int(start), int(end)

    @staticmethod
    def _dig_date(ts) -> str:
        """timestamp → 'YYYY-MM-DD' (дата сниппета; без времени)."""
        try:
            return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return ""

    @staticmethod
    def _dig_not_found(query: str) -> str:
        """Честный JSON-контракт при отсутствии попаданий (БЛОК 2.8/R16):
        нули + текст «ничего не нашёл» — БЕЗ выдуманных цифр.

        Сохраняет обратную совместимость по подстроке «ничего не нашёл по
        запросу» (снапшот-тесты: plain→JSON обновлены осознанно)."""
        return json.dumps({
            "total_mentions": 0,
            "mentions_by_authors": {},
            "first_seen": None,
            "last_seen": None,
            "snippets": [],
            "facts": [],
            "status": "not_found",
            "message": f"ничего не нашёл по запросу «{query}»",
        }, ensure_ascii=False)

    @staticmethod
    def _dig_person_text(raw) -> str | None:
        """person → строка ≤ _DIG_PERSON_MAX_CHARS (None — пусто)."""
        text = str(raw or "").strip()
        if not text:
            return None
        return text[:_DIG_PERSON_MAX_CHARS]

    def _dig_person_terms(self, person: str | None
                          ) -> tuple[int | None, list[str]]:
        """(user_id|None, OR-токены) для person: алиас-значение (casefold) →
        user_id (фильтр по user_id строк FTS); формы имени — OR-токены
        (ключевые слова = person-имя; фолбэк каскада в обратную сторону)."""
        if person is None:
            return None, []
        aliases = self.deps.aliases
        mapping = getattr(aliases, "_aliases", None)
        person_uid = None
        if isinstance(mapping, dict) and mapping:
            low = person.casefold()
            for key, value in mapping.items():
                if str(value).casefold() == low:
                    try:
                        person_uid = int(key)
                    except (TypeError, ValueError):
                        person_uid = None
                    break
        return person_uid, keywords(person)

    # ── helpers ───────────────────────────────────────────────────

    def _require_query(self, arguments: dict, ctx: ToolContext) -> str:
        """query из аргументов (fallback — исходное сообщение юзера)."""
        raw = arguments.get("query")
        text = str(raw or "").strip() if isinstance(raw, str) else str(raw or "").strip()
        return text or ctx.query

    @staticmethod
    def _require_str(arguments: dict, key: str) -> str:
        """Строковый аргумент инструмента (None/не-строка → "")."""
        raw = arguments.get(key)
        if raw is None:
            return ""
        return str(raw).strip()

    def _resolve_name(self, row: dict) -> str:
        """Имя автора строки FTS: алиас → имя → ник → user_id (R7-каскад)."""
        user_id = row.get("user_id")
        if self.deps.aliases is not None and user_id is not None:
            try:
                return self.deps.aliases.resolve(
                    int(user_id), (row.get("author_name") or None), None)
            except (TypeError, ValueError):
                pass
        author = str(row.get("author_name") or "").strip()
        if author:
            return author
        return str(user_id) if user_id is not None else "кто-то"
