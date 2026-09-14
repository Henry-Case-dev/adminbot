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
"""
import asyncio
import datetime
import json
import logging
import re
import time

from config.settings import settings
from services import hot_config as hot
from services.media_send import send_media, send_quality_menu
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
)
from services.search_aggregator import AllSearchEnginesFailedException
from services.smartmodule_urls import extract_youtube_video_id
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
# Cap транскрипта для mode=transcript (прецедент handlers/youtube T-690).
_SUMMARIZE_TRANSCRIPT_CAP = 20000

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
                 download_cooldown=None) -> None:
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


class ToolContext:
    """Контекст вызова инструментов (одно сообщение direct_chat).

    Раунд 10.15 (F8): bot/reply_to_message_id/user_id — аддитивные
    keyword-only (у download_media есть куда отправить файл и на что
    ответить реплаем).
    """

    def __init__(self, chat_id: int, query: str, *, bot=None,
                 reply_to_message_id=None, user_id=None) -> None:
        self.chat_id = chat_id
        self.query = str(query or "")
        self.bot = bot
        self.reply_to_message_id = reply_to_message_id
        self.user_id = user_id


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
            rag = await self.deps.memory.get_rag_context(ctx.chat_id, query)
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
        if not merged:
            return f"ничего не нашёл по запросу «{query}»"
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
                    stamp = f" {self._dig_date(ts)}" if ts else ""
                    msg_lines.append(f"[{name}{stamp}]: {text}")
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
                        _format_origin_labeled_line,
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
                            # F1/T-1420 (spec §3.6): единый RAG-рендер факта
                            # «[{label}] [ММ.ГГГГ | Автор: X] текст (возможно
                            # устарело)» — тот же хелпер, что и в RAG-контексте.
                            # Автор — target_user строки (R16, не выдумываем).
                            ts_render = ts if ts else None
                            fact_lines.append(_format_origin_labeled_line((
                                row.get("origin"), text, ts_render,
                                row.get("target_user"))))
                            if len(fact_lines) >= max_facts:
                                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stage_error = f"{type(exc).__name__}"
                logger.warning("[tools] dig facts failed | query=%r | "
                               "error=%s", query, stage_error, exc_info=True)
        parts: list[str] = []
        if msg_lines:
            parts.append("сообщения:\n" + "\n".join(msg_lines))
        if fact_lines:
            parts.append("факты:\n" + "\n".join(fact_lines))
        if not parts:
            if stage_error:
                return (f"ОШИБКА dig_into_lore: этап поиска не выполнен "
                        f"({stage_error})")
            return f"ничего не нашёл по запросу «{query}»"
        return _truncate("\n".join(parts), dig_max_symbols)

    # ── F8 (раунд 10.15, ADR-1015-3): новые инструменты ──────────────

    async def _summarize_video(self, arguments: dict, ctx: ToolContext) -> str:
        """Выжимка/расшифровка видео по ссылке: YouTube → каскад/субтитры
        YoutubeSummarizerService; иная ссылка → мультимодальная выжимка
        (summarize_media_url). mode=transcript → сырой текст (cap), иначе
        summary. Не-URL → ОШИБКА. Результат усечён до _MEMORY_MAX_SYMBOLS.
        R17: URL не логируется."""
        url = self._require_str(arguments, "url")
        if not _is_http_url(url):
            return "ОШИБКА summarize_video: некорректная ссылка"
        mode = str(arguments.get("mode") or "summary").strip().lower()
        if mode not in ("summary", "transcript"):
            mode = "summary"
        service = self.deps.video
        if service is None:
            return "ОШИБКА summarize_video: сервис недоступен"
        try:
            if mode == "transcript":
                text = await asyncio.wait_for(
                    self._video_transcript(service, url),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
            else:
                text = await asyncio.wait_for(
                    self._video_summary(service, url, ctx),
                    timeout=_SUMMARIZE_TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[tools] summarize_video timeout | mode=%s", mode)
            return "ОШИБКА summarize_video: timeout"
        except Exception as exc:
            logger.warning("[tools] summarize_video failed | mode=%s | "
                           "error=%s", mode, type(exc).__name__)
            return f"ОШИБКА summarize_video: {type(exc).__name__}"
        text = str(text or "").strip()
        if not text:
            return "ОШИБКА summarize_video: пустой результат"
        return _truncate(text, _MEMORY_MAX_SYMBOLS)

    @staticmethod
    async def _video_transcript(service, url: str) -> str:
        """mode=transcript: субтитры YouTube (cap). Иная ссылка без транскрипта
        (для не-YouTube нужен downloader+STT — вне tool-контракта)."""
        video_id = extract_youtube_video_id(url)
        if video_id is None:
            raise ValueError("transcript доступен только для YouTube")
        return await service.engine.fetch_transcript(
            video_id, _SUMMARIZE_TRANSCRIPT_CAP, on_retry=None)

    @staticmethod
    async def _video_summary(service, url: str, ctx: ToolContext) -> str:
        """mode=summary: YouTube → каскад выжимки по video_id; прямая/платформа
        → мультимодальная выжимка по video_url."""
        video_id = extract_youtube_video_id(url)
        if video_id is not None:
            return await service.summarize_cascade(video_id,
                                                   chat_id=ctx.chat_id)
        return await service.summarize_media_url(chat_id=ctx.chat_id,
                                                 video_url=url)

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
        url = self._require_str(arguments, "url")
        if not _is_http_url(url):
            return _download_status("error", "Некорректная ссылка")
        if not hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):
            return _download_status("error", "Скачивание отключено")
        if ctx.bot is None or self.deps.downloader is None:
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
        """Строки smart_messages → список «Имя: текст» (R16-каскад имён;
        пустой текст без медиа пропускается; медиа-событие — маркером)."""
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
            lines.append(f"{self._resolve_name(item)}: {text}")
        return lines

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
