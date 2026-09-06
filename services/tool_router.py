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
"""
import asyncio
import datetime
import logging
import re
import time

from config.settings import settings
from services import hot_config as hot
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

# Bugfix 04.09.2026 (Часть 2, 3.3(г)): человечные лейблы окна для заголовка
# счётчика query_chat_memory.
_TIME_RANGE_LABELS = {
    "last_day": "за сутки",
    "last_week": "за неделю",
    "last_month": "за месяц",
    "all": "за всё время",
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
                    from services.summary_memory import build_fts_query
                    match = build_fts_query(merged)
                    if match:
                        rows = await db.search_graph_facts_fts(
                            ctx.chat_id, match,
                            limit=max_facts * 3,
                            now_ts=int(time.time()),
                            include_direct_reply=False)
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
                            # D-9/§3.2.1 п.6: рендер «факт ГГГГ-ММ-ДД: текст»
                            # (дата rag_ts = COALESCE(message_timestamp,
                            # created_at)); без даты — голый текст.
                            stamp = self._dig_date(ts) if ts else ""
                            fact_lines.append(f"факт {stamp}: {text}"
                                              if stamp else text)
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
