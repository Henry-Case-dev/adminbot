"""S1 round1026 — алгоритмический префильтр Саммари (ADR-1026-1).

**Чистый** модуль (0 LLM-вызовов, без БД/сети/системных часов): балльный
алгоритм §88 (4 критерия, максимум 1 балл за критерий), порог §87,
всплеск по плотности §89 и механическая часть §93 (оценка токенного объёма
+ перекрывающиеся фрагменты + дедуп по ``id``).

Границы (ADR-1026-1):
  * D2 — Δ DDL = 0; модуль не касается хранилища.
  * D4 — детерминизм: вход сортируется по ``(timestamp, id)``; всплеск
    считается по времени сообщений, а не системным часам.
  * D5 — семантическое «объединить темы/устранить семантические дубли»
    относится к S3; здесь только механический дедуп по ``id``.
  * D6 — фильтруется только XML-история L1; ``dropped`` сохраняется для S2.

Поля строки окна (``get_window_messages``): ``id`` (DB), ``tg_message_id``
(Telegram), ``reply_to_id`` (Telegram id родителя — см.
``handlers/summary.py:181-183``), ``user_id``, ``text``, ``timestamp``,
``media_type``, ``author_name``.
"""
from __future__ import annotations

import dataclasses
import logging
import re
import time

from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

# §87/§88: «адресное упоминание» — детерминированная эвристика по тексту
# (в строке окна нет поля `mentions`; `reply_to_id` — основной сигнал).
_MENTION_RE = re.compile(r"@[A-Za-z0-9_]{3,}")

# §93: перекрытие фрагментов по умолчанию — 1 сообщение (хвост предыдущего
# фрагмента повторяется в начале следующего; последние сообщения не режутся).
DEFAULT_FRAGMENT_OVERLAP = 1

# Максимально возможный балл (критериев ровно 4).
MAX_SCORE = 4


@dataclasses.dataclass(frozen=True)
class FilterParams:
    """Параметры префильтра (резолвятся из каталога `summary_filter_*`)."""

    min_weight: int = 1
    min_words_for_bonus: int = 5
    burst_window_seconds: int = 120
    min_burst_density: int = 4
    reply_context_enabled: bool = True


@dataclasses.dataclass(frozen=True)
class Fragment:
    """Механический перекрывающийся фрагмент (§93, контракт для S3)."""

    index: int
    message_ids: tuple
    overlap_message_ids: tuple
    reason: str


@dataclasses.dataclass(frozen=True)
class FilterResult:
    """Результат фильтрации. ``kept``/``dropped`` — АСК-хронология полных
    строк входа; ``fragments`` — ``None`` («влезает») либо список Fragment;
    ``restored_count`` зарезервирован (S2), в S1 всегда 0."""

    kept: list
    dropped: list
    fragments: list | None
    source_count: int
    saved_count: int
    restored_count: int
    drop_percent: float
    counts: dict
    scores: dict
    budget: dict
    status: str
    duration_ms: float


# ── Доступ к полям строки (sqlite3.Row | dict | объект) ────────────────────

def _row_get(row, name):
    if row is None:
        return None
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, None)


def _row_id(row):
    return _row_get(row, "id")


def _row_tg(row):
    return _row_get(row, "tg_message_id")


def _row_user(row):
    return _row_get(row, "user_id")


def _row_reply(row):
    return _row_get(row, "reply_to_id")


def _row_text(row):
    value = _row_get(row, "text")
    return "" if value is None else str(value)


def _row_ts(row):
    value = _row_get(row, "timestamp")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_bot(row, bot_id) -> bool:
    if bot_id is None:
        return False
    return _row_user(row) == bot_id


def _has_mention(text: str) -> bool:
    return _MENTION_RE.search(text or "") is not None


def _word_count(text: str) -> int:
    return len((text or "").split())


def _is_trigger(row, trigger_message_id) -> bool:
    if trigger_message_id in (None, "", 0):
        return False
    tg = _row_tg(row)
    if tg is None:
        return False
    try:
        return int(tg) == int(trigger_message_id)
    except (TypeError, ValueError):
        return False


# ── Индексы и всплеск по плотности (§87/§88) ───────────────────────────────

def _build_children_by_tg(rows, bot_id) -> dict:
    """``tg_message_id`` родителя → число детей в окне.

    Индексируется по **Telegram** ``tg_message_id`` (``reply_to_id`` хранит
    Telegram id). Строки с ``tg_message_id is None`` не образуют родителя;
    сообщения бота/прошлых Саммари исключены (ADR-1026-1 D4/§91).
    """
    parent_tg = set()
    for row in rows:
        if _is_bot(row, bot_id):
            continue
        tg = _row_tg(row)
        if tg is not None:
            parent_tg.add(tg)
    children_by_tg: dict = {}
    for row in rows:
        if _is_bot(row, bot_id):
            continue
        parent = _row_reply(row)
        if parent is None:
            continue
        if parent in parent_tg:
            children_by_tg[parent] = children_by_tg.get(parent, 0) + 1
    return children_by_tg


def _burst_ids(rows, params: FilterParams, bot_id) -> set:
    """Trailing-окно ``[t - burst_window_seconds, t]``: сообщение в всплеске,
    если число строк окна в интервале (включая само) ≥ ``min_burst_density``
    (``==`` порога → всплеск). Два соседних сообщения при дефолте — не всплеск.

    Асимметрия trailing-окна (fail-open в сторону более поздних; ранние
    добираются S2). Сообщения бота исключены из членства (ADR-1026-1 D4).
    """
    window = max(0, int(params.burst_window_seconds))
    density = max(1, int(params.min_burst_density))
    marked: set = set()
    left = 0
    for right in range(len(rows)):
        t = _row_ts(rows[right])
        while left <= right and t - _row_ts(rows[left]) > window:
            left += 1
        if (right - left + 1) >= density and not _is_bot(rows[right], bot_id):
            marked.add(_row_id(rows[right]))
    return marked


def score_message(row, *, children_by_tg, burst_ids, params: FilterParams,
                  bot_id=None) -> int:
    """Балл сообщения 0..4 (максимум 1 балл за критерий):

    1. ``reply_to_id != None`` **или** текстовое ``@``-упоминание;
    2. на сообщение кто-то ответил в окне (только при
       ``reply_context_enabled``);
    3. сообщение во всплеске по плотности;
    4. слов в тексте **>** ``min_words_for_bonus`` (строго).

    Сообщения бота/прошлых Саммари (``user_id == bot_id``) → 0.
    """
    if _is_bot(row, bot_id):
        return 0
    score = 0
    if _row_reply(row) is not None or _has_mention(_row_text(row)):
        score += 1
    if params.reply_context_enabled:
        tg = _row_tg(row)
        if tg is not None and children_by_tg.get(tg, 0) > 0:
            score += 1
    if _row_id(row) in burst_ids:
        score += 1
    if _word_count(_row_text(row)) > int(params.min_words_for_bonus):
        score += 1
    return score


# ── Механическая оценка объёма и фрагменты (§93/D5) ────────────────────────

def estimate_and_split(kept, *, token_limit=None, char_limit=None):
    """Оценить объём ``kept`` и, если «не влезает», нарезать на
    перекрывающиеся фрагменты по границам сообщений.

    Возвращает ``(fragments | None, budget)``. Приоритет — токены
    (``token_limit``), иначе символы (``char_limit``). Последний фрагмент
    всегда заканчивается последним ``kept`` — «не отрезать последние
    сообщения молча».
    """
    rows = list(kept or [])
    if token_limit is not None:
        kind, limit = "tokens", int(token_limit)
        units = [count_tokens(_row_text(r)) for r in rows]
    elif char_limit is not None:
        kind, limit = "chars", int(char_limit)
        units = [len(_row_text(r)) for r in rows]
    else:
        tokens = sum(count_tokens(_row_text(r)) for r in rows)
        return None, {"fits": True, "estimated_tokens": tokens,
                      "limit": 0, "kind": "tokens"}

    estimated = sum(units)
    budget = {"fits": estimated <= limit, "estimated_tokens": estimated,
              "limit": limit, "kind": kind}
    if estimated <= limit or not rows:
        return None, budget

    fragments: list = []
    start = 0
    total = len(rows)
    overlap = max(0, int(DEFAULT_FRAGMENT_OVERLAP))
    while start < total:
        end = start
        acc = 0
        # Одно сообщение длиннее лимита всё равно кладётся в свой фрагмент
        # (без потери — status/лог сообщает о бюджете).
        while end < total and (acc + units[end] <= limit or end == start):
            acc += units[end]
            end += 1
        if start > 0 and overlap:
            ov_start = max(0, start - overlap)
            message_ids = tuple(_row_id(r) for r in rows[ov_start:end])
            overlap_ids = tuple(_row_id(r) for r in rows[ov_start:start])
        else:
            message_ids = tuple(_row_id(r) for r in rows[start:end])
            overlap_ids = ()
        fragments.append(Fragment(
            index=len(fragments), message_ids=message_ids,
            overlap_message_ids=overlap_ids, reason="token_budget"))
        if end >= total:
            break
        start = max(start + 1, end - overlap)
    return fragments, budget


# ── Главная функция ────────────────────────────────────────────────────────

def _sort_rows(rows):
    """АСК-хронология с тай-брейком ``(timestamp, id)`` (§D4)."""
    def key(row):
        rid = _row_id(row)
        try:
            rid_key = int(rid)
        except (TypeError, ValueError):
            rid_key = 0
        return (_row_ts(row), rid_key)
    return sorted(rows, key=key)


def filter_window(rows, params: FilterParams | None = None, *, bot_id=None,
                  trigger_message_id=None, token_limit=None,
                  char_limit=None) -> FilterResult:
    """Отфильтровать окно §87–§88 и оценить объём §93.

    Fail-open (ADR-1026-1 D4/D6): любое исключение → ``status='error'``,
    ``kept = rows`` (нефильтрованное окно). Пустой ``kept`` при непустом
    входе → ``status='empty_fallback'``, ``kept = rows``. ``trigger_message_id``
    форсированно сохраняется. Ничего не выбрасывается безвозвратно —
    ``dropped`` доступен для S2.
    """
    params = params or FilterParams()
    raw = list(rows or [])
    source_count = len(raw)
    t0 = time.perf_counter()
    try:
        source = _sort_rows(raw)
        children_by_tg = _build_children_by_tg(source, bot_id)
        burst_ids = _burst_ids(source, params, bot_id)
        try:
            threshold = max(0, min(int(params.min_weight), MAX_SCORE))
        except (TypeError, ValueError):
            threshold = 1

        scores: dict = {}
        counts = {"mention_or_reply": 0, "answered": 0, "burst": 0, "long": 0,
                  "bot_excluded": 0}
        kept: list = []
        dropped: list = []
        for row in source:
            score = score_message(
                row, children_by_tg=children_by_tg, burst_ids=burst_ids,
                params=params, bot_id=bot_id)
            scores[_row_id(row)] = score
            if _is_bot(row, bot_id):
                counts["bot_excluded"] += 1
            else:
                if _row_reply(row) is not None or _has_mention(_row_text(row)):
                    counts["mention_or_reply"] += 1
                tg = _row_tg(row)
                if (params.reply_context_enabled and tg is not None
                        and children_by_tg.get(tg, 0) > 0):
                    counts["answered"] += 1
                if _row_id(row) in burst_ids:
                    counts["burst"] += 1
                if _word_count(_row_text(row)) > int(params.min_words_for_bonus):
                    counts["long"] += 1
            if score >= threshold or _is_trigger(row, trigger_message_id):
                kept.append(row)
            else:
                dropped.append(row)

        status = "ok"
        if not kept and source:
            # Fail-open против тихой потери окна (§4.3 п.5).
            kept = source
            dropped = []
            status = "empty_fallback"

        fragments, budget = estimate_and_split(
            kept, token_limit=token_limit, char_limit=char_limit)
    except Exception:
        logger.warning("summary filter: internal error — fail-open | rows=%d",
                       source_count, exc_info=True)
        duration = (time.perf_counter() - t0) * 1000.0
        return FilterResult(
            kept=raw, dropped=[], fragments=None,
            source_count=source_count, saved_count=source_count,
            restored_count=0, drop_percent=0.0,
            counts={"mention_or_reply": 0, "answered": 0, "burst": 0, "long": 0,
                    "bot_excluded": 0},
            scores={},
            budget={"fits": True, "estimated_tokens": 0, "limit": 0,
                    "kind": "tokens"},
            status="error", duration_ms=duration)

    drop_percent = (
        round(100.0 * len(dropped) / source_count, 1) if source_count else 0.0)
    duration = (time.perf_counter() - t0) * 1000.0
    return FilterResult(
        kept=kept, dropped=dropped, fragments=fragments,
        source_count=source_count, saved_count=len(kept), restored_count=0,
        drop_percent=drop_percent, counts=counts, scores=scores,
        budget=budget, status=status, duration_ms=duration)
