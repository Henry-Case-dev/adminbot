"""Раунд 10.20 (БЛОК 1, ADR-1020-4 п.2/п.3 + ADR-1020-6) — «Летописец».

Изолированный синтез истории: сервис собирает JSON-контракт
``{graph_facts, chronological_dialogs, статистика}`` из двух шагов
(Шаг А — срез графа ``db.lore_graph_slice``, Шаг Б — плотная хронология
``db.lore_dense_dialogs``), прогоняет его через собственный канон
``LORE_STORY_SYSTEM_PROMPT`` (HTML-разметка — О5, иначе канон DirectChat
обрезал бы историю до 1-2 предложений) и возвращает готовый рассказ.

UPD/диффы (T-1891): hit по ``(chat_id, normalize_text(topic))`` →
``is_update=true`` + ``previous_story_at``; в промпт идёт сохранённая
«Известная база» + только новые сообщения (``ts > last_ts``) и ветка
UPD (Свежак). Историю пишем в аддитивную ``lore_stories`` (без бампа
``user_version``, О7); ошибки БД → WARNING + деградация без UPD (NFR-4).

R17: в логах — только chat_id/длины/is_update, без текстов истории.
"""
from __future__ import annotations

import datetime
import logging
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.canonical_context import (
    format_context_item,
    resolve_item_id,
    resolve_timezone,
    split_context_header,
)
from services import mca_gates
from services.lore_prompts import (
    LORE_STORY_SYSTEM_PROMPT,
    build_lore_story_user,
)
from services.smart_cache import normalize_text
from services.summary_memory import _stale_suffix, build_fts_query

logger = logging.getLogger(__name__)

# Код-константы (каталог-Δ=0; прецедент _MEMORY_MAX_SYMBOLS/_HISTORY_*).
_LORE_TOPIC_MAX_CHARS = 200
_LORE_STORY_TEMPERATURE = 0.85
_LORE_GRAPH_MAX_FACTS = 30
_LORE_GRAPH_MAX_SYMBOLS = 4000
_LORE_DIALOGS_MAX = 3
_LORE_DIALOG_WINDOW_MINUTES = 30
_LORE_DIALOG_MAX_SYMBOLS = 6000
_LORE_TOPIC_MIN_TOKEN = 3

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def _empty_dense() -> dict:
    """S10.20-15: свежий срез на каждый вызов (раньше `dict(_EMPTY_DENSE)`
    шарил один и тот же список `dialogs` между вызовами — латентная ловушка)."""
    return {"earliest": None, "latest": None, "total": 0, "dialogs": []}


def topic_tokens(topic: str) -> list[str]:
    """Токены топика для FTS/граф-матча (>=3 символов, уникальные, порядок
    исходника — детерминизм)."""
    out: list[str] = []
    for token in _TOKEN_RE.findall(str(topic or "").casefold()):
        if len(token) >= _LORE_TOPIC_MIN_TOKEN and token not in out:
            out.append(token)
    return out


class LoreCompilerService:
    """Сборка лора + синтез истории инструментом (8-й tool)."""

    def __init__(self, db, llm, aliases=None, tz_name=None) -> None:
        self.db = db
        self.llm = llm
        self.aliases = aliases
        # S10.20-14: tz чата для статистики «первое/последнее упоминание»
        # (пусто → UTC, прежнее поведение).
        self.tz_name = str(tz_name or "")

    async def compile(self, chat_id: int, topic: str) -> dict:
        """→ ``{"status": "ok", "is_update": bool, "story": str, ...}``.

        Контракт ошибок: ``{"status": "not_found"|"error", "message": ...}``
        (честный отказ без LLM-вызова). Исключения LLM уходят наверх
        (роутер деградирует в «ОШИБКА …») — здесь не глотаются."""
        clean = str(topic or "").strip()[:_LORE_TOPIC_MAX_CHARS]
        if not clean:
            return {"status": "error", "message": "не указан topic"}
        tokens = topic_tokens(clean)
        match = build_fts_query(tokens) if tokens else ""
        topic_key = normalize_text(clean)

        previous = await self.db.get_lore_story(chat_id, topic_key)
        since = int(previous.get("last_ts") or 0) if previous else 0

        graph = await self.db.lore_graph_slice(
            chat_id, clean, depth=2, max_facts=_LORE_GRAPH_MAX_FACTS)
        graph_lines = self._trim(self._graph_facts(graph),
                                 _LORE_GRAPH_MAX_SYMBOLS)

        dense = _empty_dense()
        stats: dict = {}
        measure_result: dict | None = None
        measure_query = None
        k1_stats = mca_gates.chat_statistics_enabled()
        if match:
            dense = await self.db.lore_dense_dialogs(
                chat_id, match, max_dialogs=_LORE_DIALOGS_MAX,
                window_minutes=_LORE_DIALOG_WINDOW_MINUTES, since_ts=since)
            if k1_stats:
                # MCA-15 (T-4926, §24.1 п.9): агрегаты «Летописца» — через
                # `chat_statistics` (тот же измерительный контур); «упоминаний:
                # N» не выдаётся за точное число фразы без метода/единицы.
                from services import chat_statistics as _cs
                measure_query = _cs.StatsQuery(
                    chat_id=chat_id, metric=_cs.METRIC_MESSAGES,
                    match_mode=_cs.MATCH_PREFIX, terms=tuple(tokens),
                    interval_from=(since + 1 if since else None),
                    timezone=self.tz_name)
                measure_result = await _cs.measure(self.db, measure_query)
                bounds = measure_result.get("time_bounds") or {}
                stats = {"count": measure_result.get("value"),
                         "first_seen": bounds.get("first_seen"),
                         "last_seen": bounds.get("last_seen")}
            else:
                stats = await self.db.search_messages_fts_count_by_author(
                    chat_id, match, since_ts=(since + 1 if since else 0))
        metric_result = None
        if k1_stats and measure_result is not None:
            from services import chat_statistics as _cs2
            metric_result = _cs2.build_metric_result(measure_result,
                                                     measure_query)

        # S10.20-5: last_ts — по ФАКТИЧЕСКИ включённому в промпт материалу
        # (макс. ts усечённых dialog-строк), а не по глобальным агрегатам
        # (иначе сообщения, не попавшие в окна/кап, выпадали из UPD навсегда).
        dialog_pairs = self._trim_pairs(
            self._dialog_pairs(dense.get("dialogs") or []),
            _LORE_DIALOG_MAX_SYMBOLS)
        dialog_lines = [line for line, _ in dialog_pairs]
        included_last_ts = max((ts for _, ts in dialog_pairs), default=0)
        total_new = int(dense.get("total") or 0)

        if not previous and not graph_lines and not dialog_lines:
            logger.info("[lore] not_found | chat=%s | tokens=%d",
                        chat_id, len(tokens))
            return {"status": "not_found",
                    "message": f"По теме «{clean}» в памяти ничего не нашлось."}

        if previous and not dialog_lines and not total_new:
            # UPD-путь без нового материала: отдаём сохранённую базу без
            # повторного (дорогого) LLM-вызова — честное «ничего не изменилось».
            # MCA-15 (T-4932, §7.3): старые агрегаты истории не проверены этим
            # ходом → stats_recheck=True (перепроверка — повторной компиляцией;
            # lore не удаляется), numeric-гард direct снимет непроверенные числа.
            logger.info("[lore] update no-new-data | chat=%s", chat_id)
            return {"status": "ok", "is_update": True, "unchanged": True,
                    "story": str(previous.get("story") or ""),
                    "previous_story_at": previous.get("updated_at"),
                    "stats_recheck": bool(metric_result is not None
                                          or k1_stats),
                    "metric_result": None}

        authors = self._mentions_by_authors(stats)
        if k1_stats:
            total_mentions, authors_list, stats_label, stats_method = (
                self._measure_stats_for_prompt(measure_result))
        else:
            total_mentions = int(stats.get("count") or total_new)
            authors_list, stats_label, stats_method = None, "", ""
        user = build_lore_story_user(
            topic=clean, graph_facts=graph_lines, dialogs=dialog_lines,
            total_mentions=total_mentions,
            mentions_by_authors=(authors if not k1_stats else None),
            authors=authors_list,
            stats_label=stats_label, stats_method=stats_method,
            first_seen=self._date(stats.get("first_seen") or dense.get("earliest"),
                                  self.tz_name),
            last_seen=self._date(stats.get("last_seen") or dense.get("latest"),
                                 self.tz_name),
            previous_story=(previous.get("story") if previous else None))
        system = LORE_STORY_SYSTEM_PROMPT.replace("{topic}", clean)

        started = time.monotonic()
        story = await self.llm.generate(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            temperature=_LORE_STORY_TEMPERATURE, chat_id=chat_id)
        story = str(story or "").strip()
        if not story:
            return {"status": "error", "message": "пустой ответ модели"}

        last_ts = max(since, included_last_ts)
        await self.db.upsert_lore_story(chat_id, topic_key, clean, story,
                                        last_ts)
        # mca-05 фасад (ADR-1027-12 D8): ленивый legacy-маппинг при
        # касании — БЕЗ автоматической ложной склейки (связь только по
        # подтверждённой event-связи; unmapped виден с честным unknown).
        # Fail-open: ошибка фасада не рвёт инструмент компилятора.
        try:
            from services import mca_gates as _gates
            if _gates.episodes_compiler_facade_enabled():
                from services.mca_episodes import note_compiler_touch
                saved = await self.db.get_lore_story(chat_id, topic_key)
                if saved:
                    await note_compiler_touch(chat_id, dict(saved),
                                              llm=self.llm)
        except Exception:
            logger.warning("[lore] legacy facade touch failed", exc_info=True)
        logger.info(
            "[lore] story ok | chat=%s | is_update=%s | graph=%d | dialogs=%d "
            "| out_chars=%d | latency_ms=%.0f", chat_id, bool(previous),
            len(graph_lines), len(dialog_lines), len(story),
            (time.monotonic() - started) * 1000.0)
        return {"status": "ok", "is_update": bool(previous), "story": story,
                "previous_story_at": (previous.get("updated_at")
                                      if previous else None),
                "stats_recheck": False,
                "metric_result": metric_result}

    # ── рендер Шага А/Шага Б ──────────────────────────────────────────────

    def _graph_facts(self, graph: dict) -> list[str]:
        """Факты/Убеждения (по ``edge.fact_id``) + рёбра без факта — в
        каноническом виде ``format_context_item(kind="fact")``. Факты уже
        отсортированы БД ASC; рёбра-без-факта идут после, порядок по
        (source, target, relation) из БД — детерминизм (R16: пустые поля
        опускаются, автор/ID не выдумываются)."""
        lines: list[str] = []
        covered: set = set()
        for fact in graph.get("facts") or []:
            text = str(fact.get("fact") or "").strip()
            if not text:
                continue
            fact_id = int(fact.get("id") or 0)
            covered.add(fact_id)
            ts = int(fact.get("rag_ts") or 0) or None
            lines.append(format_context_item(
                ts=ts, author=fact.get("target_user"),
                item_id=resolve_item_id(fact_id=fact_id), text=text,
                kind="fact", stale=bool(_stale_suffix(ts))))
        for edge in graph.get("edges") or []:
            if edge.get("fact_id") and int(edge["fact_id"]) in covered:
                continue
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            relation = str(edge.get("relation_type") or "").strip()
            if not (source or target):
                continue
            text = f"{source} --[{relation}]--> {target}".strip()
            lines.append(format_context_item(
                author=(source or None), item_id=None, text=text,
                kind="fact"))
        return lines

    def _dialog_pairs(self, dialogs: list) -> list[tuple[str, int]]:
        """Окна диалогов (строго ASC от БД) → ``(каноническая строка, ts)``;
        пустой текст без медиа пропускается, медиа-событие — маркером
        (прецедент `tool_router._history_lines`). S10.20-5: ts нужен, чтобы
        `last_ts` считался по фактически включённому материалу."""
        pairs: list[tuple[str, int]] = []
        for window in dialogs or []:
            for row in window or []:
                item = dict(row) if row is not None else {}
                text = str(item.get("text") or "").strip()
                if not text:
                    media = str(item.get("media_type") or "").strip()
                    if not media or media == "text":
                        continue
                    text = f"[медиа: {media}]"
                forward_source = (item.get("forward_source")
                                  if item.get("is_forward") else None)
                line = format_context_item(
                    ts=item.get("timestamp"), author=self._resolve_name(item),
                    item_id=resolve_item_id(
                        tg_message_id=item.get("tg_message_id"),
                        message_id=item.get("id")),
                    forward_source=forward_source, text=text, kind="msg")
                try:
                    ts = int(item.get("timestamp") or 0)
                except (TypeError, ValueError):
                    ts = 0
                pairs.append((line, ts))
        return pairs

    def _dialog_lines(self, dialogs: list) -> list[str]:
        """Строки окон (обёртка над ``_dialog_pairs`` — обратная совместимость)."""
        return [line for line, _ in self._dialog_pairs(dialogs)]

    # ── хелперы ───────────────────────────────────────────────────────────

    def _mentions_by_authors(self, stats: dict) -> dict:
        """``by_author`` FTS-счётчика → {имя: count} тем же R16-каскадом, что
        `tool_router._resolve_name` (алиас → имя → user_id).

        Только K1 OFF (паритет 2.58.55): K1 ON использует типизированные
        ``authors`` измерения (ключ — канонический user_id, имя — подпись)."""
        out: dict = {}
        for entry in (stats or {}).get("by_author") or []:
            name = self._resolve_name(entry)
            out[name] = out.get(name, 0) + int(entry.get("count") or 0)
        return out

    @staticmethod
    def _measure_stats_for_prompt(
            result: dict | None) -> tuple[int, list | None, str, str]:
        """measure-результат `chat_statistics` → (число, авторы, ярлык, метод).

        Ошибка/unsupported/частичное-без-числа → 0/None/"" — непроверенный
        агрегат в промпт не попадает. ``partial`` с числом — число + пометка
        «(частично)» (число не выдаётся за полное)."""
        if not isinstance(result, dict):
            return 0, None, "", ""
        status = str(result.get("status") or "")
        value = result.get("value")
        if status not in ("ok", "partial") or value is None:
            return 0, None, "", ""
        label = "сообщений с совпадением"
        if status == "partial":
            label += " (частично)"
        method = str(result.get("method_label")
                     or result.get("method") or "")
        return (int(value), list(result.get("authors") or []), label, method)

    def _resolve_name(self, row: dict) -> str:
        """Имя автора: алиас → author_name → user_id (R7-каскад, R16)."""
        user_id = row.get("user_id")
        if self.aliases is not None and user_id is not None:
            try:
                return self.aliases.resolve(
                    int(user_id), (row.get("author_name") or None), None)
            except (TypeError, ValueError):
                pass
        author = str(row.get("author_name") or "").strip()
        if author:
            return author
        return str(user_id) if user_id is not None else "кто-то"

    @staticmethod
    def _date(ts, tz_name: str = "") -> str:
        """unix ts → ``YYYY-MM-DD`` в tz чата (S10.20-14: `time.gmtime` давал
        UTC — статистика «первое/последнее упоминание» могла расходиться на
        сутки с диалогом)."""
        if not ts:
            return ""
        try:
            seconds = int(ts)
        except (TypeError, ValueError):
            return ""
        if not seconds:
            return ""
        resolved = resolve_timezone(tz_name, fallback="UTC")
        try:
            moment = datetime.datetime.fromtimestamp(
                seconds, datetime.timezone.utc).astimezone(ZoneInfo(resolved))
        except (ValueError, OSError, OverflowError, ZoneInfoNotFoundError):
            return ""
        return moment.strftime("%Y-%m-%d")

    @staticmethod
    def _trim_pairs(pairs: list[tuple[str, int]], cap: int) -> list[tuple[str, int]]:
        """Обрезка ``(строка, ts)`` по суммарному бюджету символов.

        S10.20-8/M1: у последней строки НЕ режется канонический заголовок
        (метаданные неприкосновенны) — `split_context_header` отделяет header
        и усекает только body; если body-бюджета нет — строка отбрасывается."""
        budget = max(0, int(cap or 0))
        out: list[tuple[str, int]] = []
        used = 0
        for text, ts in pairs:
            text = str(text or "")
            if used + len(text) > budget:
                room = budget - used
                header, body = split_context_header(text)
                if not header:
                    break
                room_body = room - len(header)
                if room_body <= 0:
                    break
                out.append((header + body[:room_body], ts))
                break
            out.append((text, ts))
            used += len(text) + 1
        return out

    @staticmethod
    def _trim(lines: list[str], cap: int) -> list[str]:
        """Обрезка списка строк по бюджету символов (header-safe, S10.20-8)."""
        return [line for line, _ in LoreCompilerService._trim_pairs(
            [(line, 0) for line in lines], cap)]
