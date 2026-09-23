"""S2 round1026 — детерминированное восстановление контекста Саммари
(ADR-1026-4, Эпик 2 «Summary Hybrid Pipeline», §90–§92).

**Чистый** модуль (0 LLM-вызовов, без БД/сети/системных часов): достраивает
вокруг сохранённых фильтром сообщений (``FilterResult.kept``, S1) обратимо
отброшенный контекст (``dropped``) и полное окно:

* **reply-родители** — транзитивно по ``reply_to_id`` (Telegram id родителя),
  включая проход **сквозь бот-ответы**; родители **вне окна** подаются
  async-адаптером генератора как ``extra_parents`` (там переиспользуется
  канонический ``services/thread_chain.collect_thread_chain`` — вторая
  реализация обхода цепочки не создаётся, ADR-1026-4 D1/D7);
* **ограниченный ближайший контекст** — до ``context_neighbors`` строк окна с
  каждой стороны от якоря (только из ``dropped``);
* единая **ASC-хронология** ``(timestamp, id)``, дедуп по ``id``, сохранение
  исходных ``id``/``tg_message_id``/``reply_to_id`` (§92);
* жёсткий **cap** на добавляемые (``context_max_messages``) и общий
  токенный/символьный **бюджет** (``token_limit``/``char_limit``) — любое
  усечение даёт ``status='truncated'`` + ``skipped_ids`` («не резать молча»,
  §93); ``kept`` не удаляется никогда.

Границы (ADR-1026-4):
  * **D2** — семантика тем/«объединить темы/устранить дубли» — S3;
    ``FilterResult.fragments`` здесь не потребляются.
  * **D3** — ``restored_count`` = число **добавленных** после дедупа/cap/бюджета.
  * **D5** — бот-ответы и прошлые Саммари (``user_id == bot_id``) не
    восстанавливаются как события; медиа/подписи/транскрипты сохраняются;
    ``mentions`` не выдумывается.

Поля строки окна (``get_smart_window``): ``id`` (DB), ``tg_message_id``
(Telegram), ``reply_to_id`` (Telegram id родителя), ``user_id``, ``text``,
``timestamp``, ``media_type``, ``author_name``, ``is_forward``,
``forward_source``.
"""
from __future__ import annotations

import dataclasses
import logging
import time

from services.database import row_get
from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

# §90/ADR-1026-4 D4: максимальная глубина прохода reply-цепочки в адаптере
# (переиспользуется как граница и в чистом обходе по окну).
RESTORE_CHAIN_DEPTH = 10

# §92: канонические поля структурированного входа L1 (S3).
_L1_FIELDS = (
    "message_id",
    "chat_id",
    "timestamp",
    "author_id",
    "display_name",
    "text",
    "reply_to_id",
    "message_type",
)


@dataclasses.dataclass(frozen=True)
class RestoreParams:
    """Параметры восстановления (резолвятся из существующих ключей S1 §89)."""

    context_neighbors: int = 1          # §89: соседей С КАЖДОЙ стороны от якоря
    context_max_messages: int = 50      # §89: cap на ДОБАВЛЯЕМЫЕ сообщения


@dataclasses.dataclass(frozen=True)
class RestoreResult:
    """Аддитивный результат S2 (не расширение ``FilterResult``, ADR-1026-4 D1).

    ``kept`` — финал для ``summary_xml.build`` (S1.kept ∪ restored, ASC, без
    дублей); ``restored`` — только добавленные строки; ``budget`` — оценка
    объёма ``kept ∪ restored``.
    """

    kept: list
    restored: list
    restored_count: int
    parent_count: int
    neighbor_count: int
    restored_tg_ids: tuple
    skipped_ids: tuple
    budget: dict
    status: str
    duration_ms: float


# ── Доступ к полям строки ──────────────────────────────────────────────────

def _row_id(row):
    return row_get(row, "id")


def _row_tg(row):
    return row_get(row, "tg_message_id")


def _row_user(row):
    return row_get(row, "user_id")


def _row_reply(row):
    return row_get(row, "reply_to_id")


def _row_text(row):
    value = row_get(row, "text")
    return "" if value is None else str(value)


def _row_ts(row):
    try:
        return int(row_get(row, "timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _is_bot(row, bot_id) -> bool:
    if bot_id is None:
        return False
    return _row_user(row) == bot_id


def _sort_key(row):
    """ASC-хронология с детерминированным тай-брейком ``(timestamp, id)``."""
    rid = _row_id(row)
    try:
        rid_key = int(rid)
    except (TypeError, ValueError):
        rid_key = 0
    return (_row_ts(row), rid_key)


def _key(row):
    """Ключ дедупа: DB-``id`` → ``tg_message_id`` → идентичность объекта."""
    rid = _row_id(row)
    if rid is not None:
        return ("id", rid)
    tg = _row_tg(row)
    if tg is not None:
        return ("tg", tg)
    return ("obj", id(row))


def _int_or(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _index_by_tg(rows) -> dict:
    """``tg_message_id`` → строка (первое вхождение в ASC-порядке)."""
    index: dict = {}
    for row in rows:
        tg = _row_tg(row)
        if tg is None:
            continue
        if tg not in index:
            index[tg] = row
    return index


def _unit(row, kind: str) -> int:
    text = _row_text(row)
    return count_tokens(text) if kind == "tokens" else len(text)


# ── Ядро: reply-родители ───────────────────────────────────────────────────

def _walk_parents(anchor, win_by_tg, extra_by_tg, bot_id, kept_keys,
                  out: list, seen: set) -> None:
    """Транзитивная цепочка ``reply_to_id`` от ``anchor``.

    Родитель, уже присутствующий в окне, берётся из ``win_by_tg``; родитель вне
    окна / сквозь бот-ответ — из ``extra_by_tg`` (данные async-адаптера).
    Бот-строки и уже сохранённые (``kept``) не добавляются, но цепочка сквозь
    них продолжается (§91/D5).
    """
    current = anchor
    for _ in range(max(0, RESTORE_CHAIN_DEPTH)):
        parent_tg = _row_reply(current)
        if parent_tg is None:
            return
        parent = win_by_tg.get(parent_tg)
        if parent is None:
            parent = extra_by_tg.get(parent_tg)
        if parent is None:
            return
        pkey = _key(parent)
        if _is_bot(parent, bot_id):
            current = parent
            continue
        if pkey in kept_keys or pkey in seen:
            current = parent
            continue
        seen.add(pkey)
        out.append(parent)
        current = parent


# ── Ядро: ограниченный соседний контекст ───────────────────────────────────

def _collect_neighbors(anchors, window_sorted, pos_by_id, dropped_ids,
                       kept_keys, added_keys, neighbors, bot_id) -> list:
    """До ``neighbors`` строк окна с каждой стороны от каждого якоря.

    Кандидаты — только из ``dropped`` (S1), не бот, не дубли ``kept``/уже
    добавленных. Порядок детерминирован: сначала offset=1 по всем якорям
    (близость), затем offset=2 и т.д.; внутри — ASC-хронология якорей,
    предшественник раньше последователя.
    """
    if neighbors <= 0:
        return []
    anchors_sorted = sorted(anchors, key=_sort_key)
    out: list = []
    seen = set(added_keys)
    for offset in range(1, neighbors + 1):
        for anchor in anchors_sorted:
            pos = pos_by_id.get(_key(anchor))
            if pos is None:
                continue
            for idx in (pos - offset, pos + offset):
                if idx < 0 or idx >= len(window_sorted):
                    continue
                cand = window_sorted[idx]
                ckey = _key(cand)
                if ckey in seen or ckey in kept_keys:
                    continue
                if ckey not in dropped_ids:
                    continue
                if _is_bot(cand, bot_id):
                    continue
                seen.add(ckey)
                out.append(cand)
    return out


# ── Публичная чистая функция ───────────────────────────────────────────────

def restore_context(kept, dropped, window, params: RestoreParams | None = None,
                    *, extra_parents=(), token_limit=None, char_limit=None,
                    bot_id=None) -> RestoreResult:
    """Восстановить контекст вокруг ``kept`` (§90, ADR-1026-4 D1/D4).

    Порядок применения: **родители → соседи → cap → бюджет**. Входные списки
    не мутируются. Fail-open: любое исключение → ``status='error'`` и
    ``kept = list(kept)`` (S1-выход, без тихой потери).
    """
    params = params or RestoreParams()
    t0 = time.perf_counter()
    raw_kept = list(kept or [])
    try:
        kept_sorted = sorted(raw_kept, key=_sort_key)
        window_sorted = sorted(list(window or []), key=_sort_key)
        dropped_ids = {_key(r) for r in (dropped or [])}
        win_by_tg = _index_by_tg(window_sorted)
        extra_by_tg = _index_by_tg(sorted(list(extra_parents or []), key=_sort_key))

        kept_keys = {_key(r) for r in kept_sorted}
        pos_by_id: dict = {}
        for i, row in enumerate(window_sorted):
            pos_by_id.setdefault(_key(row), i)

        # 1. reply-родители (высший приоритет).
        parents: list = []
        parent_seen: set = set()
        for anchor in kept_sorted:
            _walk_parents(anchor, win_by_tg, extra_by_tg, bot_id, kept_keys,
                          parents, parent_seen)

        # 2. ограниченные соседи (якоря: kept + восстановленные родители).
        neighbor_rows = _collect_neighbors(
            kept_sorted + parents, window_sorted, pos_by_id, dropped_ids,
            kept_keys, parent_seen, max(0, _int_or(params.context_neighbors, 0)),
            bot_id)

        # Приоритет отбора: родители → соседи (по близости, уже упорядочены).
        additions = parents + neighbor_rows
        skipped: list = []
        truncated = False

        # 3. жёсткий cap на добавляемые (§89).
        cap = max(0, _int_or(params.context_max_messages, 50))
        if len(additions) > cap:
            skipped.extend(additions[cap:])
            additions = additions[:cap]
            truncated = True

        # 4. общий бюджет kept ∪ restored (§93): усекаем только добавляемые.
        if token_limit is not None:
            kind, limit, enforce = "tokens", _int_or(token_limit, 0), True
        elif char_limit is not None:
            kind, limit, enforce = "chars", _int_or(char_limit, 0), True
        else:
            kind, limit, enforce = "tokens", 0, False

        if enforce:
            total = sum(_unit(r, kind) for r in kept_sorted)
            units = [_unit(r, kind) for r in additions]
            total += sum(units)
            while additions and total > limit:
                removed = additions.pop()
                total -= units.pop()
                skipped.append(removed)
                truncated = True
            budget = {"fits": total <= limit, "estimated_tokens": total,
                      "limit": limit, "kind": kind}
        else:
            total = sum(count_tokens(_row_text(r))
                        for r in kept_sorted + additions)
            budget = {"fits": True, "estimated_tokens": total, "limit": 0,
                      "kind": "tokens"}

        # Финал: единая ASC-хронология + дедуп по id; kept не удаляется.
        seen_final: set = set()
        final: list = []
        for row in sorted(kept_sorted + additions, key=_sort_key):
            k = _key(row)
            if k in seen_final:
                continue
            seen_final.add(k)
            final.append(row)

        restored = sorted(additions, key=_sort_key)
        parent_keys = {_key(r) for r in parents}
        parent_count = sum(1 for r in restored if _key(r) in parent_keys)
        neighbor_count = len(restored) - parent_count
        restored_tg_ids = tuple(
            _row_tg(r) for r in restored if _row_tg(r) is not None)
        skipped_ids = tuple(
            _row_id(r) for r in skipped if _row_id(r) is not None)

        if truncated:
            status = "truncated"
        elif restored:
            status = "ok"
        else:
            status = "no_candidates"

        return RestoreResult(
            kept=final, restored=restored, restored_count=len(restored),
            parent_count=parent_count, neighbor_count=neighbor_count,
            restored_tg_ids=restored_tg_ids, skipped_ids=skipped_ids,
            budget=budget, status=status,
            duration_ms=(time.perf_counter() - t0) * 1000.0)
    except Exception:
        logger.warning(
            "summary context restore: internal error — fail-open | kept=%d",
            len(raw_kept), exc_info=True)
        return RestoreResult(
            kept=list(raw_kept), restored=[], restored_count=0, parent_count=0,
            neighbor_count=0, restored_tg_ids=(), skipped_ids=(),
            budget={"fits": True, "estimated_tokens": 0, "limit": 0,
                    "kind": "tokens"},
            status="error", duration_ms=(time.perf_counter() - t0) * 1000.0)


# ── §92: структурированный вход L1 (S3) ────────────────────────────────────

def build_l1_payload(rows, chat_id) -> list:
    """Структурированные сообщения §92 для L1-кластеризатора (S3).

    Используются **только фактически доступные** поля строки окна:
    ``message_id ← tg_message_id``, ``author_id ← user_id``,
    ``display_name ← author_name``, ``message_type ← media_type``,
    ``reply_to_id``, ``timestamp``, ``text``; ``chat_id`` — из контекста
    запуска. Отсутствующие метаданные не выдумываются: ``mentions`` (поля в
    окне нет) в элемент не попадает вовсе.
    """
    payload: list = []
    for row in rows or []:
        item = {
            "message_id": _row_tg(row),
            "chat_id": chat_id,
            "timestamp": row_get(row, "timestamp"),
            "author_id": _row_user(row),
            "display_name": row_get(row, "author_name"),
            "text": row_get(row, "text"),
            "reply_to_id": _row_reply(row),
            "message_type": row_get(row, "media_type"),
        }
        mentions = row_get(row, "mentions")
        if mentions is not None:
            item["mentions"] = mentions
        payload.append(item)
    return payload
