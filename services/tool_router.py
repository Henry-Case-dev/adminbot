"""Эпик 04.09.2026 (3.3, Часть 2) — исполнение инструментов Tool Calling.

Фиксированный реестр имён (dispatch по таблице, БЕЗ исполнения произвольного
кода); аргументы валидируются (кривой JSON/тип → текст ошибки); результаты
режутся (4000/3500 симв.); параллельного исполнения НЕТ (последовательно, по
одному tool_call за раунд — бюджет в tool_loop).

dispatch ВСЕГДА возвращает строку результата (в т.ч. 'ОШИБКА …') — НЕ бросает
(FR-14: результат ошибки уходит модели как role:"tool").
"""
import asyncio
import datetime
import logging
import re
import time

from services.search_aggregator import AllSearchEnginesFailedException

logger = logging.getLogger(__name__)

# Лимиты результатов инструментов (3.3): символы.
_SEARCH_MAX_SYMBOLS = 4000
_MEMORY_MAX_SYMBOLS = 3500
_MEMORY_FTS_LIMIT = 40
_MEMORY_VEC_LIMIT = 15
# Бюджет одного инструмента веб-поиска (сумма таймаутов каскада + запас).
_SEARCH_TOOL_TIMEOUT = 25.0

# Окна query_chat_memory (3.3): time_range → секунды (0 = всё время).
_TIME_RANGE_SECONDS = {
    "last_day": 24 * 3600,
    "last_week": 7 * 24 * 3600,
    "last_month": 30 * 24 * 3600,
    "all": 0,
}

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def keywords(query: str) -> list[str]:
    """Токены запроса для FTS-поиска (L2-путь query_chat_memory)."""
    return _TOKEN_RE.findall(str(query or "").lower())


def _time_range_since(time_range: str) -> int:
    """Секунды с эпохи для окна (0 = без фильтра по времени)."""
    seconds = _TIME_RANGE_SECONDS.get((time_range or "all").strip().lower(), 0)
    return 0 if not seconds else int(time.time()) - seconds


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


class ToolDeps:
    """Контейнер зависимостей инструментов (инжектится из bot.py)."""

    def __init__(self, search, memory, aliases=None) -> None:
        self.search = search            # SearchAggregator
        self.memory = memory            # MemoryManager
        self.aliases = aliases          # AliasResolver | None


class ToolContext:
    """Контекст вызова инструментов (одно сообщение direct_chat)."""

    def __init__(self, chat_id: int, query: str) -> None:
        self.chat_id = chat_id
        self.query = str(query or "")


class ToolRouter:
    """Реестр исполнения инструментов (3.3). Никогда не бросает."""

    def __init__(self, deps: ToolDeps) -> None:
        self.deps = deps

    async def dispatch(self, name: str, arguments: dict, ctx: ToolContext) -> str:
        """→ строка результата инструмента (в т.ч. 'ОШИБКА …') — НЕ бросает."""
        registry = {
            "execute_web_search": self._execute_web_search,
            "query_chat_memory": self._query_chat_memory,
        }
        method = registry.get(name)
        if method is None:
            logger.warning("[tools] unknown tool | name=%s", name)
            return f"ОШИБКА: неизвестный инструмент {name}"
        try:
            return await method(arguments, ctx)
        except Exception as exc:
            logger.warning("[tools] exec failed | tool=%s | error=%s",
                           name, f"{type(exc).__name__}: {exc}")
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
        for row in rows:
            ts = _format_timestamp(row.get("timestamp"))
            if since and int(row.get("timestamp") or 0) < since:
                continue
            name = self._resolve_name(row)
            stamp = f" [{ts}]" if ts else ""
            text = str(row.get("text") or "").strip()
            if text:
                lines.append(f"[{name}{stamp}]: {text}")

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

        if not lines:
            return f"По запросу «{query}» в памяти ничего не найдено."
        return _truncate("\n".join(lines), _MEMORY_MAX_SYMBOLS)

    # ── helpers ───────────────────────────────────────────────────

    def _require_query(self, arguments: dict, ctx: ToolContext) -> str:
        """query из аргументов (fallback — исходное сообщение юзера)."""
        raw = arguments.get("query")
        text = str(raw or "").strip() if isinstance(raw, str) else str(raw or "").strip()
        return text or ctx.query

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
