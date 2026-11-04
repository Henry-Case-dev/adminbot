"""ASAP-3 (round 1028, ADR-1028-2 D3–D7) — единый Direct Context Composer.

Consumer-side Direct Chat (Summary НЕ импортирует; §0). Чистое ядро:
приоритет-модель P0–P3, eviction P3→P2→P1, границы old-verbatim-эпизода
(0 LLM, детерминированно), importance-aware выбор unsummarized middle и
process-local метрики/диагностика. Оркестрация (сборка кандидатов сущест-
вующими билдерами, materialize в канонические блоки) — в
`DirectChatService._compose_user_content` (порядок блоков payload не
меняется — совместимость промпта «важное к концу»).

Kill-switch: `DIRECT_CONTEXT_COMPOSER_ENABLED` (env ClassVar, default ON;
OFF → байт-в-байт прежний контекст-путь, без новых событий/счётчиков —
проверяется parity-тестами).

Инварианты (§51):
  * no fake unlimited; no hidden 32k (без `resolve_context_tokens` для -1);
  * важный контекст (P0) не удаляется обычным budgeter'ом;
  * recent tail ≥ CHAT_FRESH_TAIL_MIN_MESSAGES (P1-пол, P2 не вытесняет);
  * old relevant episode — verbatim coherent span (`<Old_Episode>`, P0);
  * summary = background (P2); «всё влезает — не режем» (§16);
  * physical overflow — явная деградация, никакого silent `text[:N]` (§17).
R17: наружу только id/enum/числа; сырой текст в события/логи не попадает.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace as _dc_replace

from config.settings import settings
from services import hot_config as hot
from services import model_capacity
from services.model_capacity import (
    WINDOW_SOURCE_ENV, WINDOW_SOURCE_FALLBACK, WINDOW_SOURCE_MAP,
)
from services.agentic_events import (
    CONTEXT_CAPACITY, CONTEXT_PHYSICAL_OVERFLOW, CONTEXT_PRESSURE,
    CONTEXT_SELECT, CONTEXT_TAIL_FLOOR_CLAMPED, DIRECT_SILENT_ACK,
    DIRECT_SILENT_ACK_FAILED, DIRECT_TRIGGER, emit_agentic_event,
)
from services.token_counter import (
    append_protected_spans, count_tokens, has_protected_spans,
    truncate_to_tokens, truncate_to_tokens_keep_head,
)

logger = logging.getLogger(__name__)

COMPOSER_POLICY_VERSION = "asap3-composer-1"

# ── Приоритет-модель (§8 × §12; сквозная карта spec §3.4, D-PM-7) ───────────
P0 = 0        # MUST KEEP: current/replied/branch/target/relations/protected/lore/episode
P1 = 1        # fresh verbatim tail; <Conversation_Thread>; strong episodes
P2 = 2        # running summary (background); Global head; RAG; history_supplement (P0-HA: вне-диапазонное дополнение); level-2; map; nostalgia; mood
P3 = 3        # middle-подбор; слабый фон; anchors (стиль)

# kind → приоритет (канонические kind'и блоков сервиса + части композера).
BLOCK_PRIORITY: dict[str, int] = {
    # P0
    "current": P0,
    "target": P0,
    "relations": P0,
    "protected": P0,
    "lore": P0,
    "branch": P0,
    "episode": P0,
    "sandwich": P0,
    # EVOL v5 §12.2 (DIRECT-SELF-CORRECTION-01): рамка возражения на СВОЙ
    # прошлый ответ — P0: роли (своё утверждение / возражение / источник)
    # не вытесняются под давлением окна, иначе поведение §12 откатывается.
    "correction": P0,
    # P1
    "global_tail": P1,
    "thread": P1,
    # P2
    "global_head": P2,
    "rag": P2,
    # P0-HA ISOLATION (§3): вне-диапазонное дополнение — P2 (как RAG и
    # конспект, НЕ P0); под давлением окна вытесняется раньше периода.
    "history_supplement": P2,
    "map": P2,
    "nostalgia": P2,
    "mood": P2,
    # P3
    "global_middle": P3,
    "anchors": P3,
}

# Стратегии внутреннего усечения piece'ов:
#   "end"  — рез жертвы со стороны СТАРЫХ строк (fresh tail / thread / middle);
#   "head" — keep-head (конспект держится — running summary);
#   "span" — importance-удержание строк (эпизод/branch: маркеры важности).
PIECE_KEEP: dict[str, str] = {
    "global_tail": "end",
    "global_middle": "end",
    "thread": "end",
    "global_head": "head",
    "episode": "span",
    "branch": "span",
    # P0-HA ISOLATION: баннер дополнения — голова piece'а, удерживается
    # при внутренней усечении (сам piece P2 — вытесняется целиком раньше
    # периода).
    "history_supplement": "head",
}

# Канонический порядок слотов materialize (порядок блоков payload НЕ меняется
# — совместимость с промптом «важное к концу»; D3). Отсутствующие блоки
# просто не занимают слот; позиции детерминированы kind'ом.
CANONICAL_ORDER: dict[str, int] = {
    "map": 0,
    "branch": 1,
    "episode": 2,
    # P0-HA ISOLATION (§3): слот дополнения сразу после episode;
    # последующие индексы сдвинуты на +1 (относительный порядок прежних
    # kind'ов не меняется — порядок блоков payload тот же).
    "history_supplement": 3,
    "rag": 4,
    "global_head": 5,
    "global_middle": 6,
    "global_tail": 7,
    "thread": 8,
    "target": 9,
    "relations": 10,
    "protected": 11,
    "lore": 12,
    "nostalgia": 13,
    "mood": 14,
    # EVOL v5 §12.2 (DIRECT-SELF-CORRECTION-01): слот рамки возражения —
    # сразу перед текущей репликой («важное к концу»); относительный порядок
    # прежних kind'ов сохранён (последующие сдвинуты на +1).
    "correction": 15,
    "current": 16,
    "anchors": 17,
    "sandwich": 18,
}


def composer_on() -> bool:
    """Kill-switch `DIRECT_CONTEXT_COMPOSER_ENABLED` (default ON, per-call,
    никогда не бросает). OFF → точный прежний direct behavior."""
    try:
        return bool(getattr(settings, "DIRECT_CONTEXT_COMPOSER_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(getattr(settings, name, default))
    except Exception:      # pragma: no cover - защитная ветка
        value = default
    return max(minimum, value)


def fresh_tail_min_messages() -> int:
    """`CHAT_FRESH_TAIL_MIN_MESSAGES` (env, default 20) — P1-пол tail."""
    return _env_int("CHAT_FRESH_TAIL_MIN_MESSAGES", 20, 1)


def middle_max_messages() -> int:
    """`CHAT_MIDDLE_MAX_MESSAGES` (env, default 60) — top-K middle."""
    return _env_int("CHAT_MIDDLE_MAX_MESSAGES", 60, 1)


def thread_walk_max() -> int:
    """`CHAT_THREAD_WALK_MAX` (env, default 40) — hard-cap walk до корня."""
    return _env_int("CHAT_THREAD_WALK_MAX", 40, 1)


def episode_gap_seconds() -> int:
    """`CHAT_EPISODE_GAP_SECONDS` (env, default 300)."""
    return _env_int("CHAT_EPISODE_GAP_SECONDS", 300, 1)


def episode_max_messages() -> int:
    """`CHAT_EPISODE_MAX_MESSAGES` (env, default 40)."""
    return _env_int("CHAT_EPISODE_MAX_MESSAGES", 40, 1)


def episode_max_count() -> int:
    """`CHAT_EPISODE_MAX_COUNT` (env, default 2) — эпизодов на run."""
    return _env_int("CHAT_EPISODE_MAX_COUNT", 2, 1)


def tail_floor_tokens(tail_text: str, floor_messages: int) -> int:
    """H2/D6: токены последних ``floor_messages`` непустых строк tail'а —
    РЕАЛЬНЫЙ wiring пола fresh verbatim tail для piece'а ``global_tail``
    (минимум `CHAT_FRESH_TAIL_MIN_MESSAGES`, резервируется на всех путях
    давления; ниже — только путь §17 с событием). Чистая функция."""
    lines = [ln for ln in str(tail_text or "").split("\n") if ln.strip()]
    if not lines:
        return 0
    keep_n = min(max(1, int(floor_messages)), len(lines))
    return count_tokens("\n".join(lines[-keep_n:]))


# ── Pieces: единица аллокации ────────────────────────────────────────────────

@dataclass
class ContextPiece:
    """Кандидат контекста с приоритетом и стратегией внутреннего усечения."""
    key: str                  # стабильный id piece'а ("thread", "global_tail"…)
    kind: str                 # канонический kind блока (лог/диагностика)
    text: str
    priority: int = P2
    keep: str = "end"         # "end" | "head" | "span"
    floor_tokens: int = 0     # минимум токенов (не режется ниже пока есть P2/P3)
    evictable: bool = True    # P0 → False (обычный budgeter не трогает)
    position: int = 0         # слот канонического порядка (materialize)

    def tokens(self) -> int:
        return count_tokens(self.text)


@dataclass
class AllocationResult:
    """Итог аллокации: piece'ы, статистика давления/переполнения."""
    pieces: list[ContextPiece] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)   # kind/reason/tokens
    compressed_or_dropped: int = 0
    physical_overflow: bool = False
    preserved_kinds: list[str] = field(default_factory=list)
    needed: int = 0
    available: int = 0


def truncate_lines_keep_end(lines: list[str], max_tokens: int) -> list[str]:
    """Рез со стороны СТАРЫХ строк до max_tokens (keep-end, целые строки)."""
    kept: list[str] = []
    total = 0
    for line in reversed(lines):
        cost = count_tokens(line) + (1 if kept else 0)
        if kept and total + cost > max_tokens:
            break
        kept.append(line)
        total += cost
    kept.reverse()
    return kept


def truncate_lines_keep_start(lines: list[str], max_tokens: int) -> list[str]:
    """Keep-head по целым строкам (конспект: голова держится)."""
    kept: list[str] = []
    total = 0
    for line in lines:
        cost = count_tokens(line) + (1 if kept else 0)
        if kept and total + cost > max_tokens:
            break
        kept.append(line)
        total += cost
    return kept


def truncate_piece_text(text: str, max_tokens: int, keep: str) -> str:
    """Усечение piece'а существующими механиками (без `text[:N]`):
    end → целые строки со стороны старых; head → keep-head строками;
    span → importance-обрезка + protected spans (token_counter)."""
    if max_tokens <= 0 or not text:
        return ""
    if keep == "span" and has_protected_spans(text) \
            and count_tokens(text) > max_tokens:
        base = truncate_to_tokens(text, max(1, max_tokens - 48))
        return append_protected_spans(base, text, max_tokens)
    if keep == "head":
        return truncate_to_tokens_keep_head(text, max_tokens)
    if keep == "span":
        # importance-удержание через trim_verbatim_lines — на стороне
        # сервиса (строки уже отрисованы каноном); здесь — keep-end строк.
        return "\n".join(truncate_lines_keep_end(
            text.split("\n"), max_tokens))
    return "\n".join(truncate_lines_keep_end(text.split("\n"), max_tokens))


def allocate_budget(pieces: list[ContextPiece], budget: int, *,
                    measure=count_tokens, truncator=None) -> AllocationResult:
    """D3: распределение бюджета — eviction P3→P2→P1 (геометрическими
    шагами, с floors); P0 обычным budgeter'ом не трогается. «Всё помещается —
    не режем» (§16). Перераспределение неявное: режется только под pressure.

    ``truncator(piece, limit) -> str`` — необязательная стратегия усечения
    вызывающего (сервис передаёт `_truncate_block` с protected spans/тегами;
    None → встроенный `truncate_piece_text`)."""
    result = AllocationResult(pieces=list(pieces), available=max(1, int(budget)))
    total = sum(p.tokens() for p in result.pieces)
    if total <= budget:
        return result
    reduce_fn = truncator or (
        lambda piece, limit: truncate_piece_text(piece.text, limit,
                                                 piece.keep))
    # M-ASAP3-1: полурезка (compression без дропа) — тоже pressure-сигнал;
    # жертвы считаются по одному разу на piece.
    victims: set[int] = set()
    tiers = (P3, P2, P1)
    for tier in tiers:
        for piece in result.pieces:
            if total <= budget:
                break
            if piece.priority != tier or not piece.evictable:
                continue
            floor = max(0, int(piece.floor_tokens))
            initial = piece.tokens()
            guard = 0
            while total > budget and guard < 12:
                guard += 1
                current = piece.tokens()
                if current <= max(1, floor):
                    break
                limit = max(floor, current // 2)
                new_text = reduce_fn(piece, limit)
                if count_tokens(new_text) >= current:
                    break               # нет прогресса → piece исчерпан
                piece.text = new_text
                total = sum(p.tokens() for p in result.pieces)
            if piece.tokens() < initial and id(piece) not in victims:
                victims.add(id(piece))
                result.compressed_or_dropped += 1
            if piece.tokens() <= max(1, floor) and floor > 0:
                # floor достигнут — дальше piece не участвует.
                continue
    # Полный дроп исчерпанных кусков низших приоритетов при остатке pressure.
    for tier in tiers:
        if total <= budget:
            break
        for piece in result.pieces:
            if total <= budget:
                break
            if piece.priority != tier or not piece.evictable \
                    or piece.floor_tokens > 0:
                continue
            if piece.text:
                if id(piece) not in victims:
                    victims.add(id(piece))
                    result.compressed_or_dropped += 1
                result.excluded.append({
                    "kind": piece.kind,
                    "reason_code": "budget_exceeded",
                    "estimated_tokens": piece.tokens()})
                piece.text = ""
                total = sum(p.tokens() for p in result.pieces)
    if total > budget:
        # §3.9: P0 + tail-floor не влезают — явная деградация (не text[:N]):
        # иерархическое сокращение secondary (branch → thread → episode) с
        # protected spans; ядро P0 (current/target/protected/replied) сохраняется.
        result.physical_overflow = True
        result.needed = total
        for kind in ("episode", "thread", "branch"):
            if total <= budget:
                break
            for piece in result.pieces:
                if total <= budget:
                    break
                if piece.kind == kind and piece.text:
                    piece.text = reduce_fn(
                        piece, max(1, piece.tokens() // 4))
                    total = sum(p.tokens() for p in result.pieces)
        for piece in result.pieces:
            if piece.text:
                result.preserved_kinds.append(piece.kind)
    # Учёт вытесненных (пустых) кусков — CONTEXT_PRESSURE/диагностика.
    for piece in result.pieces:
        if not piece.text and piece.evictable \
                and all(e["kind"] != piece.kind for e in result.excluded):
            result.excluded.append({
                "kind": piece.kind, "reason_code": "budget_exceeded",
                "estimated_tokens": 0})
    return result


# ── D4: old verbatim episode — детерминированные границы (0 LLM) ────────────

def _row_get(row, key, default=None):
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        return row[key]
    except Exception:
        return default


def _row_tg_id(row):
    tg = _row_get(row, "tg_message_id")
    try:
        return int(tg) if tg not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


def compute_episode_span(rows: list, anchor_tg_id: int | None, *,
                         gap_seconds: int = 300,
                         max_messages: int = 40,
                         max_reply_depth: int = 6
                         ) -> tuple[int, int, str] | None:
    """Границы эпизода вокруг хита (чистая функция; идемпотентная).

    rows — ASC по (timestamp, id) строки окна/выборки; anchor_tg_id —
    tg_message_id хита. Шаги D4: (1) расширение по gap ≤ ``gap_seconds``;
    (2) reply-graph closure (предки/потомки по reply_to_id, depth cap 6,
    cycle-safe); (3) склейка непрерывного [start..end] («дырки» > gap →
    split, берётся сегмент с хитом); (4) кап ``max_messages`` (окно вокруг
    хита, приоритет «до хита» 3:1). Возвращает ``(start_idx, end_idx,
    reason)`` включительно или None (якорь вне rows)."""
    if not rows or anchor_tg_id is None:
        return None
    tg_index: dict[int, int] = {}
    for idx, row in enumerate(rows):
        tg = _row_tg_id(row)
        if tg is not None and tg not in tg_index:
            tg_index[tg] = idx
    anchor_idx = tg_index.get(int(anchor_tg_id))
    if anchor_idx is None:
        return None
    ts = [int(_row_get(row, "timestamp") or 0) for row in rows]
    reason_steps: list[str] = []

    # (1) темпоральное расширение.
    start, end = anchor_idx, anchor_idx
    while start > 0 and 0 < ts[start] - ts[start - 1] <= gap_seconds:
        start -= 1
    while end < len(rows) - 1 and 0 < ts[end + 1] - ts[end] <= gap_seconds:
        end += 1
    if end > start:
        reason_steps.append("gap")

    # (2) reply-graph closure (bounded, cycle-safe).
    span_ids = {i for i in range(start, end + 1)}
    for _ in range(max(1, max_reply_depth)):
        grew = False
        # предки: reply_to_id строк span → строки вне span.
        for idx in list(span_ids):
            parent_tg = _row_tg_id_val(_row_get(rows[idx], "reply_to_id"))
            if parent_tg is not None and parent_tg in tg_index:
                pidx = tg_index[parent_tg]
                if pidx not in span_ids:
                    span_ids.add(pidx)
                    grew = True
        # потомки: строки вне span с reply_to_id внутрь span.
        for idx, row in enumerate(rows):
            if idx in span_ids:
                continue
            parent_tg = _row_tg_id_val(_row_get(row, "reply_to_id"))
            if parent_tg is not None and parent_tg in tg_index \
                    and tg_index[parent_tg] in span_ids:
                span_ids.add(idx)
                grew = True
        if not grew:
            break
    if span_ids:
        new_start, new_end = min(span_ids), max(span_ids)
        if (new_start, new_end) != (start, end):
            reason_steps.append("reply_links")
        start, end = new_start, new_end

    # (3) склейка непрерывного сегмента с хитом («дырки» > gap → split,
    # но reply-связь ЧЕРЕЗ дырку склейку держит — эпизод coherent).
    def _reply_linked_across(hole_idx: int) -> bool:
        # hole_idx — первая строка ПОСЛЕ дырки; связывает ли reply-граф
        # стороны дырки?
        right = _row_tg_id_val(_row_get(rows[hole_idx], "reply_to_id"))
        if right is not None:
            pidx = tg_index.get(right)
            if pidx is not None and start <= pidx < hole_idx:
                return True
        for idx in range(start, hole_idx):
            left = _row_tg_id_val(_row_get(rows[idx], "reply_to_id"))
            if left is not None:
                nidx = tg_index.get(left)
                if nidx is not None and hole_idx <= nidx <= end:
                    return True
        return False

    seg_start = start
    for idx in range(anchor_idx, start, -1):
        if ts[idx] - ts[idx - 1] > gap_seconds \
                and not _reply_linked_across(idx):
            seg_start = idx
            break
    else:
        seg_start = start
    seg_end = end
    for idx in range(anchor_idx, end):
        if ts[idx + 1] - ts[idx] > gap_seconds \
                and not _reply_linked_across(idx + 1):
            seg_end = idx
            break
    else:
        seg_end = end
    start, end = seg_start, seg_end

    # (4) кап сообщений: окно вокруг хита (3:1 в пользу «до хита»).
    size = end - start + 1
    reason = "+".join(reason_steps) if reason_steps else "hit"
    if size > max_messages:
        back = max(0, int(max_messages * 3 / 4))
        forward = max_messages - back - 1
        new_start = max(start, anchor_idx - back)
        new_end = min(end, anchor_idx + max(0, forward))
        if new_end < new_start:
            new_end = new_start
        start, end = new_start, new_end
        reason = (reason + "+cap_applied").lstrip("+")
    return start, end, reason


def _row_tg_id_val(value):
    try:
        return int(value) if value not in (None, "", 0) else None
    except (TypeError, ValueError):
        return None


# ── D5: importance-aware выбор unsummarized middle (bounded top-K) ──────────

def _lexical_overlap(query: str, text: str) -> int:
    import re as _re
    q_tokens = set(_re.findall(r"[а-яёa-z0-9]+", str(query or "").casefold()))
    if not q_tokens:
        return 0
    t_tokens = set(_re.findall(r"[а-яёa-z0-9]+", str(text or "").casefold()))
    return len(q_tokens & t_tokens)


def select_middle(rows: list, *, query: str, chain_tg_ids: set[int],
                  participant_ids: set[int], top_k: int
                  ) -> list:
    """Bounded top-K middle-строк (детерминированный вес: recency; членство
    в reply-цепи; участник; лексическое перекрытие). Порядок вывода —
    хронологический ASC (детерминизм, идемпотентность)."""
    if not rows or top_k <= 0:
        return []
    max_ts = max((int(_row_get(r, "timestamp") or 0) for r in rows),
                 default=0)
    scored: list[tuple[float, int, int]] = []
    for idx, row in enumerate(rows):
        weight = 0.0
        tg = _row_tg_id(row)
        if tg is not None and tg in chain_tg_ids:
            weight += 3.0
        author = _row_get(row, "user_id")
        try:
            if author is not None and int(author) in participant_ids:
                weight += 1.5
        except (TypeError, ValueError):
            pass
        weight += 2.0 * (_lexical_overlap(query, _row_get(row, "text") or "")
                         / 10.0)
        if max_ts:
            weight += 1.0 * (int(_row_get(row, "timestamp") or 0) / max_ts)
        scored.append((weight, idx, _row_tg_id(row) or 0))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    chosen = sorted(idx for _, idx, _ in scored[:max(1, int(top_k))])
    return [rows[idx] for idx in chosen]


# ── D15: счётчики §46 + grep-able строка лога ───────────────────────────────

DIRECT_METRIC_NAMES = (
    "direct_force_reply_total",
    "direct_autonomous_reply_total",
    "direct_autonomous_react_total",
    "direct_autonomous_silent_total",
    "direct_silent_ack_success_total",
    "direct_silent_ack_failed_total",
    "direct_old_episode_retrieval_total",
    "direct_context_pressure_total",
    "direct_context_physical_overflow_total",
)

_DIRECT_METRICS: dict[str, int] = {name: 0 for name in DIRECT_METRIC_NAMES}


def record_direct_metric(name: str) -> int:
    """Инкремент process-local счётчика §46 + grep-able строка
    ``direct_metric name=<…> count=<…>`` (R17: только имя/число)."""
    try:
        if name not in _DIRECT_METRICS:
            _DIRECT_METRICS[name] = 0
        _DIRECT_METRICS[name] += 1
        logger.info("direct_metric name=%s count=%d", name,
                    _DIRECT_METRICS[name])
        return _DIRECT_METRICS[name]
    except Exception:      # pragma: no cover - защитная ветка
        return 0


def direct_metrics_snapshot() -> dict[str, int]:
    """Снимок счётчиков (для /api/direct/context-diagnostics и тестов)."""
    return {name: int(_DIRECT_METRICS.get(name, 0))
            for name in DIRECT_METRIC_NAMES}


def reset_direct_metrics() -> None:
    """Тест-хелпер: обнулить счётчики (в проде не вызывается)."""
    for name in DIRECT_METRIC_NAMES:
        _DIRECT_METRICS[name] = 0


# ── Диагностика последнего прогона (miniapp §34; process-local, R17) ────────

_DIAGNOSTICS: dict[int, dict] = {}
_DIAGNOSTICS_MAX_CHATS = 64


def record_diagnostics(chat_id: int, data: dict) -> None:
    """Сохранить срез последнего ON-прогона композера по чату (только
    числа/коды; R17). Bounded: последние 64 чата (LRU-подобно)."""
    try:
        _DIAGNOSTICS.pop(int(chat_id), None)
        _DIAGNOSTICS[int(chat_id)] = dict(data or {})
        while len(_DIAGNOSTICS) > _DIAGNOSTICS_MAX_CHATS:
            _DIAGNOSTICS.pop(next(iter(_DIAGNOSTICS)))
    except Exception:      # pragma: no cover - защитная ветка
        pass


def get_diagnostics(chat_id: int) -> dict | None:
    """Последняя диагностика чата (None — прогонов не было)."""
    try:
        data = _DIAGNOSTICS.get(int(chat_id))
        return dict(data) if data else None
    except Exception:      # pragma: no cover - защитная ветка
        return None


def reset_diagnostics() -> None:
    """Тест-хелпер."""
    _DIAGNOSTICS.clear()


# ── Emission-хелперы (§32/§33; гейт AGENTIC_EVENTS_ENABLED внутри) ──────────

def emit_context_capacity(*, model: str, window: int, window_source: str,
                          external_tokens: int, output_reserve: int,
                          available_context: int, budget: int,
                          policy_mode: str, summary_revision: str | None,
                          summary_watermark, summary_lag_messages: int | None,
                          summary_age, estimation_method: str | None = None
                          ) -> None:
    """CONTEXT_CAPACITY (§32): полная вместимость прогона (числа/коды)."""
    emit_agentic_event(
        CONTEXT_CAPACITY, model=str(model or "")[:64], window=int(window),
        window_source=str(window_source),
        external_tokens=int(external_tokens),
        output_reserve=int(output_reserve),
        available_context=int(available_context), budget=int(budget),
        policy_mode=str(policy_mode),
        summary_revision=summary_revision,
        summary_watermark=summary_watermark,
        summary_lag_messages=summary_lag_messages, summary_age=summary_age,
        estimation_method=estimation_method)


def emit_context_select(*, recent_verbatim_messages: int = 0,
                        recent_verbatim_tokens: int = 0,
                        reply_thread_messages: int = 0,
                        old_episode_count: int = 0,
                        old_episode_messages: int = 0,
                        old_episode_tokens: int = 0,
                        middle_selected_messages: int = 0,
                        compressed_background_tokens: int = 0,
                        rag_tokens: int = 0, chat_id: int | None = None,
                        message_id: int | None = None) -> None:
    """CONTEXT_SELECT (§32): фактическая композиция (числа)."""
    emit_agentic_event(
        CONTEXT_SELECT, chat_id=chat_id, message_id=message_id,
        recent_verbatim_messages=int(recent_verbatim_messages),
        recent_verbatim_tokens=int(recent_verbatim_tokens),
        reply_thread_messages=int(reply_thread_messages),
        old_episode_count=int(old_episode_count),
        old_episode_messages=int(old_episode_messages),
        old_episode_tokens=int(old_episode_tokens),
        middle_selected_messages=int(middle_selected_messages),
        compressed_background_tokens=int(compressed_background_tokens),
        rag_tokens=int(rag_tokens))


def emit_context_pressure(*, excluded_low_priority: int,
                          compressed_or_dropped: int,
                          physical_overflow: bool,
                          unsummarized_tail_messages: int = 0,
                          unsummarized_tail_tokens: int = 0,
                          chat_id: int | None = None) -> None:
    """CONTEXT_PRESSURE (§32): давление бюджета (только при факте)."""
    emit_agentic_event(
        CONTEXT_PRESSURE, chat_id=chat_id,
        excluded_low_priority=int(excluded_low_priority),
        compressed_or_dropped=int(compressed_or_dropped),
        physical_overflow=bool(physical_overflow),
        unsummarized_tail_messages=int(unsummarized_tail_messages),
        unsummarized_tail_tokens=int(unsummarized_tail_tokens))


def emit_context_physical_overflow(*, preserved_kinds: list[str],
                                   available: int, needed: int,
                                   chat_id: int | None = None) -> None:
    """CONTEXT_PHYSICAL_OVERFLOW (§17/§32)."""
    emit_agentic_event(
        CONTEXT_PHYSICAL_OVERFLOW, chat_id=chat_id,
        preserved_kinds=[str(k)[:40] for k in preserved_kinds][:12],
        available=int(available), needed=int(needed))


def emit_context_tail_floor_clamped(*, chat_id: int | None,
                                    final_messages: int,
                                    floor_messages: int) -> None:
    """CONTEXT_TAIL_FLOOR_CLAMPED (H2/D6, rework round 1): давление срезало
    fresh tail до минимума CHAT_FRESH_TAIL_MIN_MESSAGES (пол engaged; ниже —
    только путь §17 с CONTEXT_PHYSICAL_OVERFLOW). Числа, R17."""
    emit_agentic_event(
        CONTEXT_TAIL_FLOOR_CLAMPED, chat_id=chat_id,
        final_messages=int(final_messages), floor_messages=int(floor_messages))


def emit_direct_trigger(*, chat_id: int | None, message_id: int | None,
                        trigger_type: str, force_reply_required: bool,
                        reply_to_bot: bool, is_private: bool,
                        addressed: bool) -> None:
    """DIRECT_TRIGGER (§30): trigger-наблюдаемость (без raw text)."""
    emit_agentic_event(
        DIRECT_TRIGGER, chat_id=chat_id, message_id=message_id,
        trigger_type=str(trigger_type),
        force_reply_required=bool(force_reply_required),
        reply_to_bot=bool(reply_to_bot), is_private=bool(is_private),
        addressed=bool(addressed))


def emit_direct_silent_ack(*, chat_id: int | None,
                           target_message_id: int | None,
                           success: bool, reason_code: str | None) -> None:
    """DIRECT_SILENT_ACK (§25/§31): реакция 🗿 на intentional silence."""
    emit_agentic_event(
        DIRECT_SILENT_ACK, chat_id=chat_id, target=target_message_id,
        reaction="🗿", success=bool(success),
        reason=str(reason_code or "")[:40] or None)


def emit_direct_silent_ack_failed(*, chat_id: int | None,
                                  target_message_id: int | None,
                                  error_code: str,
                                  reason_code: str | None = None) -> None:
    """DIRECT_SILENT_ACK_FAILED (§28): отказ ack (SILENT остаётся SILENT)."""
    emit_agentic_event(
        DIRECT_SILENT_ACK_FAILED, chat_id=chat_id,
        target=target_message_id, error_code=str(error_code)[:40],
        reason=str(reason_code or "")[:40] or None)


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED-REPLY UR-C (UR-09/10/11/13/23): ContextSelection — единый сборщик
# источников контекста с типизированными фрагментами и provenance.
#
# Контракт (arch/unified-reply-contract.md §2.2, ТЗ UR-09):
#   * порядок фрагментов ровно по UR-09: полный текущий вопрос (P0) →
#     reply-parent + ветка + правки (P0) → свежие соседи темы, ВКЛЮЧАЯ
#     собственный ответ бота как факт диалога (P1) → релевантная память (P2)
#     → конспект/широкий фон как карта тем (P2, низшее доверие) → общий
#     нерелевантный фон (P3, исключается первым);
#   * `provenance` несёт raw → selected → included + причины потери (UR-20);
#   * режет ТОЛЬКО этот allocator; P0 не режется, а при физическом
#     переполнении дробится на части со ссылкой на источник (без тихой
#     потери середины/конца, UR-10.1);
#   * `self_outputs` — обычные bot_statement из durable ledger (UR-23), без
#     style-anchor семантики.
#
# Сборка данных (окно/ветка/ledger/retrieval) — существующие модули; здесь
# только типизация, порядок, дедуп, правки/конфликты и единственная аллокация.
# ═══════════════════════════════════════════════════════════════════════════

SELECTION_POLICY_VERSION = "ur-c/selection/v1"

# ── Типы фрагментов (UR-09/UR-13.4; закрытый набор) ─────────────────────────
KIND_USER_STATEMENT = "user_statement"
KIND_CHAT_EVENT = "chat_event"
KIND_BOT_STATEMENT = "bot_statement"
KIND_SUMMARY_INFERENCE = "summary_inference"
KIND_EXTERNAL_EVIDENCE = "external_evidence"
FRAGMENT_KINDS = frozenset({
    KIND_USER_STATEMENT, KIND_CHAT_EVENT, KIND_BOT_STATEMENT,
    KIND_SUMMARY_INFERENCE, KIND_EXTERNAL_EVIDENCE,
})

# ── Авторитет (что подтверждает фрагмент) ───────────────────────────────────
AUTHORITY_PRIMARY = "primary"        # слова участника/адресата, проверенный факт
AUTHORITY_SUPPORTING = "supporting"  # «бот это говорил», событие чата
AUTHORITY_BACKGROUND = "background"  # конспект/вывод модели, устаревшая версия

# ── Роли внутри хода → приоритет UR-09 (0 = высший) ─────────────────────────
ROLE_CURRENT_QUESTION = "current_question"
ROLE_REPLY_PARENT = "reply_parent"
ROLE_THREAD = "thread"
ROLE_FRESH_NEIGHBOUR = "fresh_neighbour"
ROLE_MEMORY = "memory"
ROLE_SELF_OUTPUT = "self_output"
ROLE_SUMMARY = "summary"
ROLE_BACKGROUND = "background"

ROLE_PRIORITY: dict[str, int] = {
    ROLE_CURRENT_QUESTION: P0,
    ROLE_REPLY_PARENT: P0,
    ROLE_THREAD: P1,
    ROLE_FRESH_NEIGHBOUR: P1,
    ROLE_MEMORY: P2,
    ROLE_SELF_OUTPUT: P2,
    ROLE_SUMMARY: P2,
    ROLE_BACKGROUND: P3,
}

# Роль фиксирована порядком UR-09 — порядок вывода в payload.
ROLE_ORDER: dict[str, int] = {
    ROLE_CURRENT_QUESTION: 0,
    ROLE_REPLY_PARENT: 1,
    ROLE_THREAD: 2,
    ROLE_FRESH_NEIGHBOUR: 3,
    ROLE_MEMORY: 4,
    ROLE_SELF_OUTPUT: 5,
    ROLE_SUMMARY: 6,
    ROLE_BACKGROUND: 7,
}


def fragment_kind(kind: str | None) -> str:
    """Нормализация kind: закрытый набор UR-13.4 (неизвестное → chat_event)."""
    value = str(kind or "").strip()
    return value if value in FRAGMENT_KINDS else KIND_CHAT_EVENT


def fragment_priority(fragment: "ContextFragment") -> int:
    """Приоритет фрагмента: роль UR-09; `superseded_by` устаревшей правки
    опускает его до фона (P3), чтобы оно исчезало первым."""
    if fragment.superseded_by:
        return P3
    role = str(fragment.role or "")
    return ROLE_PRIORITY.get(role, P2)


def authority_for_kind(kind: str) -> str:
    """Авторитет по умолчанию: слова бота/событие — supporting, конспект —
    background (UR-23.5: «бот сказал» ≠ «верно в мире»)."""
    if kind == KIND_USER_STATEMENT:
        return AUTHORITY_PRIMARY
    if kind == KIND_EXTERNAL_EVIDENCE:
        return AUTHORITY_PRIMARY
    if kind == KIND_SUMMARY_INFERENCE:
        return AUTHORITY_BACKGROUND
    return AUTHORITY_SUPPORTING


@dataclass(frozen=True)
class ContextFragment:
    """Типизированный фрагмент контекста (UR-09; arch §2.2).

    ``text`` — полный текст источника; режет только allocator. ``source_id``
    — реальная ссылка (`msg:<tg>` | `bot_output:<id>` | `summary:<id>` |
    `evidence:<id>`). ``timestamp_utc`` = 0 при неизвестной дате
    (``time_known=False``): дата не выдумывается (UR-23.7)."""

    kind: str
    source_id: str
    timestamp_utc: int = 0
    speaker_uid: int | None = None
    author_label: str = ""
    text: str = ""
    reply_to: str | None = None
    authority: str = AUTHORITY_SUPPORTING
    fresh: bool = False
    # UR-23: хронология собственных/человеческих реплик без style-семантики.
    role: str = ""
    tg_message_id: int | None = None
    reply_to_tg_id: int | None = None
    correlation_id: str | None = None
    revision: int = 1
    time_known: bool = True
    media_only: bool = False
    superseded_by: str | None = None
    note: str = ""            # короткая машинная пометка (конфликт/правка)
    part_index: int = 0       # >0/part_total>1 — часть overflow-дробления
    part_total: int = 1

    @property
    def priority(self) -> int:
        return fragment_priority(self)

    def tokens(self, measure=count_tokens) -> int:
        return measure(self.text) if self.text else 0


@dataclass(frozen=True)
class SummaryMapRef:
    """Справочная карта тем: running summary + watermark (UR-12/UR-09.7).

    ``covered_to_ts``/``raw_count`` — что именно покрыто; ``new_since_ts``
    показывает, что появились новые реплики (конспект НЕ выглядит свежим без
    watermark)."""

    source_id: str
    text: str
    covered_to_ts: int = 0
    raw_count: int = 0
    new_since_ts: int = 0
    revision: str = ""
    level: int = 1


@dataclass(frozen=True)
class SelectionProvenance:
    """Наблюдаемость сборки: raw → selected → included + причины потери.

    Inspector (UR-20) читает ЭТО, а не догадывается по числу строк окна:
    «200 в UI» ≠ числу сообщений в prompt."""

    policy_version: str = SELECTION_POLICY_VERSION
    budget_tokens: int = 0
    raw_counts: dict = field(default_factory=dict)
    selected_counts: dict = field(default_factory=dict)
    included_counts: dict = field(default_factory=dict)
    dropped: tuple = ()
    raw_tokens: int = 0
    selected_tokens: int = 0
    included_tokens: int = 0
    overflow: bool = False
    overflow_parts: tuple = ()
    memory_found: bool = True
    corrections: tuple = ()
    conflicts: tuple = ()

    def as_dict(self) -> dict:
        """R17-safe срез (только коды/числа/ссылки, без текстов)."""
        return {
            "policy_version": self.policy_version,
            "budget_tokens": int(self.budget_tokens),
            "raw_counts": dict(self.raw_counts),
            "selected_counts": dict(self.selected_counts),
            "included_counts": dict(self.included_counts),
            "dropped": [dict(d) for d in self.dropped],
            "raw_tokens": int(self.raw_tokens),
            "selected_tokens": int(self.selected_tokens),
            "included_tokens": int(self.included_tokens),
            "overflow": bool(self.overflow),
            "overflow_parts": [dict(p) for p in self.overflow_parts],
            "memory_found": bool(self.memory_found),
            "corrections": [dict(c) for c in self.corrections],
            "conflicts": [dict(c) for c in self.conflicts],
        }


@dataclass(frozen=True)
class ContextSelection:
    """Единый отбор контекста для Direct/Initiative (UR-09).

    Render-проекции (`Current_Question`/`Conversation_Thread`/`Global_Context`/
    `RAG_Memory`/`Old_Episode`) собираются потребителем из этих фрагментов;
    единственный владелец усечения — :func:`allocate_selection`."""

    current_question: "ContextFragment"
    reply_parent: "ContextFragment | None" = None
    thread: tuple = ()
    memory: tuple = ()
    self_outputs: tuple = ()
    summary_map: "SummaryMapRef | None" = None
    evidence: object | None = None
    fresh_neighbours: tuple = ()
    summary: tuple = ()
    background: tuple = ()
    provenance: SelectionProvenance = field(default_factory=SelectionProvenance)

    def fragments(self) -> tuple:
        """Фрагменты в порядке UR-09 (текущий вопрос … фон)."""
        items: list = [self.current_question]
        if self.reply_parent is not None:
            items.append(self.reply_parent)
        items.extend(self.thread)
        items.extend(self.fresh_neighbours)
        items.extend(self.memory)
        items.extend(self.self_outputs)
        items.extend(self.summary)
        items.extend(self.background)
        return tuple(items)

    def as_dict(self) -> dict:
        """R17-safe срез для инспектора (UR-20): роли/типы/ссылки/числа."""
        return {
            "policy_version": SELECTION_POLICY_VERSION,
            "current_question": _fragment_ref(self.current_question),
            "reply_parent": (_fragment_ref(self.reply_parent)
                             if self.reply_parent is not None else None),
            "thread": [_fragment_ref(f) for f in self.thread],
            "fresh_neighbours": [_fragment_ref(f) for f in self.fresh_neighbours],
            "memory": [_fragment_ref(f) for f in self.memory],
            "self_outputs": [_fragment_ref(f) for f in self.self_outputs],
            "summary": [_fragment_ref(f) for f in self.summary],
            "background": [_fragment_ref(f) for f in self.background],
            "summary_map": ({
                "source_id": self.summary_map.source_id,
                "covered_to_ts": int(self.summary_map.covered_to_ts),
                "raw_count": int(self.summary_map.raw_count),
                "new_since_ts": int(self.summary_map.new_since_ts),
                "level": int(self.summary_map.level),
            } if self.summary_map is not None else None),
            "evidence": bool(self.evidence),
            "provenance": self.provenance.as_dict(),
        }


def _fragment_ref(fragment: ContextFragment) -> dict:
    """Ссылка на фрагмент без текста (R17)."""
    return {
        "source_id": fragment.source_id,
        "kind": fragment.kind,
        "role": fragment.role,
        "authority": fragment.authority,
        "timestamp_utc": int(fragment.timestamp_utc or 0),
        "time_known": bool(fragment.time_known),
        "fresh": bool(fragment.fresh),
        "speaker_uid": fragment.speaker_uid,
        "reply_to": fragment.reply_to,
        "part": (f"{fragment.part_index}/{fragment.part_total}"
                 if fragment.part_total > 1 else ""),
        "superseded_by": fragment.superseded_by,
        "note": fragment.note,
        "tokens": fragment.tokens(),
    }


def preview_text(text: str | None, limit: int) -> str:
    """UI-ВЫДЕРЖКА (UR-10.1): только отображение, НЕ вход модели.

    `limits.chat_current_question_max_chars` живёт здесь, а не на смысловом
    пути: модель получает ``ContextFragment.text`` целиком."""
    try:
        size = int(limit or 0)
    except (TypeError, ValueError):
        size = 0
    raw = str(text or "")
    if size <= 0 or len(raw) <= size:
        return raw
    return raw[:size].rstrip() + "…"


# ── Сборка фрагментов из существующих источников ────────────────────────────

def _row_value(row, key, default=None):
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        return row[key]
    except Exception:
        return default


def _alias_label(aliases, uid, fallback: str = "") -> str:
    if aliases and uid is not None:
        label = aliases.get(uid)
        if label:
            return str(label)
    return str(fallback or "")


def row_to_fragment(row, *, role: str, aliases=None, bot_user_id=None,
                    fresh: bool = False, now_ts: int = 0,
                    fresh_window_seconds: int = 0) -> ContextFragment:
    """Строка окна/эпизода → фрагмент (user_statement/chat_event)."""
    uid = _row_value(row, "user_id")
    try:
        uid = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid = None
    is_bot = bot_user_id is not None and uid is not None \
        and int(uid) == int(bot_user_id)
    tg = _row_value(row, "tg_message_id")
    try:
        tg_int = int(tg) if tg not in (None, "", 0) else None
    except (TypeError, ValueError):
        tg_int = None
    source_id = (f"bot_output_tg:{tg_int}" if is_bot and tg_int is not None
                 else (f"msg:{tg_int}" if tg_int is not None
                       else f"row:{_row_value(row, 'id', '')}"))
    text = str(_row_value(row, "text") or "")
    ts = _row_value(row, "timestamp")
    try:
        ts_int = int(ts or 0)
    except (TypeError, ValueError):
        ts_int = 0
    reply_tg = _row_value(row, "reply_to_id")
    try:
        reply_tg_int = int(reply_tg) if reply_tg not in (None, "", 0) else None
    except (TypeError, ValueError):
        reply_tg_int = None
    if fresh_window_seconds and now_ts and ts_int:
        fresh = fresh or (now_ts - ts_int) <= int(fresh_window_seconds)
    return ContextFragment(
        kind=(KIND_BOT_STATEMENT if is_bot else KIND_USER_STATEMENT),
        source_id=source_id,
        timestamp_utc=ts_int,
        speaker_uid=uid,
        author_label=_alias_label(aliases, uid,
                                  _row_value(row, "author_name") or ""),
        text=text,
        reply_to=(f"tg:{reply_tg_int}" if reply_tg_int is not None else None),
        authority=(AUTHORITY_SUPPORTING if is_bot
                   else AUTHORITY_PRIMARY),
        fresh=bool(fresh),
        role=role,
        tg_message_id=tg_int,
        reply_to_tg_id=reply_tg_int,
        time_known=bool(ts_int),
        media_only=not text.strip(),
    )


def chain_item_to_fragment(item, *, role: str, aliases=None,
                           bot_user_id=None) -> ContextFragment:
    """`thread_chain.ChainItem` → фрагмент; бот-ход = обычный bot_statement."""
    raw = str(getattr(item, "item_id", "") or "")
    tg_int = None
    if raw.startswith("tg:"):
        try:
            tg_int = int(raw[3:])
        except ValueError:
            tg_int = None
    uid = getattr(item, "uid", None)
    try:
        uid = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid = None
    is_bot = bool(getattr(item, "is_bot", False))
    text = str(getattr(item, "text", "") or "")
    ts = getattr(item, "ts", None)
    try:
        ts_int = int(ts or 0)
    except (TypeError, ValueError):
        ts_int = 0
    reply_raw = str(getattr(item, "reply_to_item_id", "") or "")
    reply_tg_int = None
    if reply_raw.startswith("tg:"):
        try:
            reply_tg_int = int(reply_raw[3:])
        except ValueError:
            reply_tg_int = None
    return ContextFragment(
        kind=(KIND_BOT_STATEMENT if is_bot else KIND_USER_STATEMENT),
        source_id=(f"bot_output_tg:{tg_int}" if is_bot and tg_int is not None
                   else (f"msg:{tg_int}" if tg_int is not None else raw or
                         "msg:unknown")),
        timestamp_utc=ts_int,
        speaker_uid=(None if is_bot else uid),
        author_label=(_alias_label(aliases, uid,
                                   getattr(item, "name", "") or "")
                      if not is_bot else str(getattr(item, "name", "") or "")),
        text=text,
        reply_to=reply_raw or None,
        authority=(AUTHORITY_SUPPORTING if is_bot
                   else AUTHORITY_PRIMARY),
        fresh=True,
        role=role,
        tg_message_id=tg_int,
        reply_to_tg_id=reply_tg_int,
        correlation_id=(str(getattr(item, "correlation_id", "") or "") or None),
        revision=int(getattr(item, "revision_no", 1) or 1),
        time_known=bool(ts_int),
        media_only=not text.strip(),
    )


def ledger_record_to_fragment(record, *, role: str = ROLE_SELF_OUTPUT,
                              aliases=None,
                              bot_user_id=None) -> ContextFragment:
    """Строка `mca_bot_outputs` → bot_statement с реальной датой/родителем.

    UR-23: собственный доставленный ответ — факт диалога (не style-anchor),
    с `tg_message_id`, `sent_at_utc`, `reply_to`, `correlation_id`, ревизией.
    Неизвестная дата (`sent_at` NULL) → `time_known=False`, ts=0 (не
    выдумываем), media-only строка остаётся без придуманного текста."""
    tg = record.get("tg_message_id")
    try:
        tg_int = int(tg) if tg not in (None, "", 0) else None
    except (TypeError, ValueError):
        tg_int = None
    output_id = record.get("output_id")
    source_id = (f"bot_output:{int(output_id)}"
                 if output_id is not None else f"bot_output_tg:{tg_int}")
    sent_at = record.get("sent_at")
    try:
        sent_int = int(sent_at or 0)
    except (TypeError, ValueError):
        sent_int = 0
    parent = str(record.get("parent_message_ref") or "")
    reply_tg_int = None
    if parent.startswith("tg:"):
        try:
            reply_tg_int = int(parent[3:])
        except ValueError:
            reply_tg_int = None
    text = str(record.get("content_text") or "")
    return ContextFragment(
        kind=KIND_BOT_STATEMENT,
        source_id=source_id,
        timestamp_utc=sent_int,
        speaker_uid=(int(bot_user_id) if bot_user_id is not None
                     else record.get("bot_user_id")),
        author_label=_alias_label(
            aliases, record.get("bot_user_id"),
            record.get("bot_name") or "бот"),
        text=text,
        reply_to=(parent or None),
        authority=AUTHORITY_SUPPORTING,
        fresh=False,
        role=role,
        tg_message_id=tg_int,
        reply_to_tg_id=reply_tg_int,
        correlation_id=(str(record.get("correlation_id"))
                        if record.get("correlation_id") else None),
        revision=int(record.get("revision_no") or 1),
        time_known=bool(sent_int),
        media_only=not text.strip(),
        note=("медиа без текста (content_ref): текст не восстановлен"
              if not text.strip() else ""),
    )


def summary_map_ref(summary_row, *, level: int = 1, now_ts: int = 0,
                    newest_ts: int = 0,
                    source_id: str | None = None) -> SummaryMapRef | None:
    """Running summary (или L2) → справочная карта тем с watermark (UR-12).

    Конспект НЕ выглядит свежим без покрытия: TTL не «забывание», актуальность
    определяется ``covered_to_ts``/``raw_count`` и наличием новых реплик."""
    if summary_row is None:
        return None
    text = str(_row_value(summary_row, "summary") or "").strip()
    if not text:
        return None
    try:
        covered_to = int(_row_value(summary_row, "window_end_ts") or 0)
    except (TypeError, ValueError):
        covered_to = 0
    try:
        raw_count = int(_row_value(summary_row, "raw_count")
                        or _row_value(summary_row, "msg_count_highwater") or 0)
    except (TypeError, ValueError):
        raw_count = 0
    new_since = 0
    if newest_ts and covered_to and int(newest_ts) > covered_to:
        new_since = int(newest_ts) - covered_to
    return SummaryMapRef(
        source_id=(source_id or
                   f"summary:{_row_value(summary_row, 'chat_id', '')}:{level}"),
        text=text, covered_to_ts=covered_to, raw_count=raw_count,
        new_since_ts=new_since,
        revision=f"{covered_to}:{raw_count}", level=int(level))


def summary_map_fragment(ref: SummaryMapRef) -> ContextFragment:
    """Карта тем → фрагмент `summary_inference` (низшее доверие, P2)."""
    note = f"пересказ, не источник; покрыто до ts={ref.covered_to_ts}"
    if ref.new_since_ts:
        note += f"; появились новые реплики после watermark ({ref.new_since_ts} c)"
    return ContextFragment(
        kind=KIND_SUMMARY_INFERENCE,
        source_id=ref.source_id,
        timestamp_utc=int(ref.covered_to_ts or 0),
        speaker_uid=None,
        author_label="конспект",
        text=ref.text,
        reply_to=None,
        authority=AUTHORITY_BACKGROUND,
        fresh=False,
        role=ROLE_SUMMARY,
        time_known=bool(ref.covered_to_ts),
        note=note)


# ── Правки и конфликты (UR-13.5) ────────────────────────────────────────────

# Фразы прямой ФАКТИЧЕСКОЙ правки (UR-13.5). Существующий
# `claim_envelope.is_correction_phrase`/`is_deny_phrase` ловит спор об
# авторстве («это говорил не я») — здесь добавляется правка значения
# («на самом деле», «точнее», «ошибся»), иначе более ранняя версия факта
# подавалась бы как равнозначная.
_FACT_CORRECTION_PATTERNS = (
    r"\bя\s+же\s+сказал", r"\bя\s+же\s+говорил", r"\bпоправк",
    r"\bточнее\b", r"\bна\s+самом\s+деле\b", r"\bошиб(ся|ка|лась)\b",
    r"\bисправляю\b", r"\bневерно\b", r"\bв\s+смысле\b",
    r"\bне\s+\d+[\d\s]*,\s*а\s+", r"\bуже\s+не\s+актуальн",
)


def _correction_phrase(text: str) -> bool:
    """Фраза-правка/возражение (REUSE существующего детектора + факт-правка)."""
    value = str(text or "")
    if not value.strip():
        return False
    try:
        from services.claim_envelope import is_correction_phrase, is_deny_phrase
        if is_correction_phrase(value) or is_deny_phrase(value):
            return True
    except Exception:          # pragma: no cover - защитная ветка
        pass
    import re as _re
    lowered = value.casefold()
    return any(_re.search(pattern, lowered)
               for pattern in _FACT_CORRECTION_PATTERNS)


def _overlap_tokens(text: str) -> set:
    import re as _re
    return set(_re.findall(r"[а-яёa-z0-9]{3,}", str(text or "").casefold()))


def detect_corrections(fragments) -> tuple[tuple, tuple]:
    """Поздняя прямая правка пользователя приоритетнее прежнего факта (UR-13.5).

    Детерминированно: более новый `user_statement` с фразой-правкой связывается
    с ближайшим по времени предыдущим `user_statement` того же автора (или
    максимальным лексическим перекрытием). Связанная старая версия получает
    ``superseded_by`` → P3 (уходит первой) и остаётся в истории как факт
    прежнего утверждения (не стирается). Возврат: ``(fragments, corrections)``.
    """
    items = list(fragments or ())
    ordered = sorted(
        ((idx, f) for idx, f in enumerate(items)
         if f.kind == KIND_USER_STATEMENT and not f.superseded_by),
        key=lambda pair: (int(pair[1].timestamp_utc or 0), pair[0]))
    corrections: list[dict] = []
    if len(ordered) < 2:
        return tuple(items), ()
    for pos, (idx, frag) in enumerate(ordered):
        if not _correction_phrase(frag.text):
            continue
        tokens = _overlap_tokens(frag.text)
        best = None
        best_score = -1.0
        for prev_idx, prev in reversed(ordered[:pos]):
            if prev.superseded_by:
                continue
            if frag.speaker_uid is not None and prev.speaker_uid is not None \
                    and int(prev.speaker_uid) != int(frag.speaker_uid):
                continue
            overlap = len(tokens & _overlap_tokens(prev.text))
            score = overlap + (0.5 if prev.speaker_uid is not None
                               and prev.speaker_uid == frag.speaker_uid else 0.0)
            if score > best_score:
                best, best_score = prev_idx, score
        if best is None or best_score <= 0:
            corrections.append({"source_id": frag.source_id,
                               "target": None,
                               "reason_code": "correction_unbound"})
            continue
        target = items[best]
        items[best] = _replace_fragment(
            target,
            superseded_by=frag.source_id,
            authority=AUTHORITY_BACKGROUND,
            note=(f"устарело: более новая правка {frag.source_id}"
                  if not target.note else
                  f"{target.note}; устарело: правка {frag.source_id}"))
        corrections.append({"source_id": frag.source_id,
                            "target": target.source_id,
                            "reason_code": "superseded_by_user_correction"})
    return tuple(items), tuple(corrections)


def _ref_digits(ref: str | None) -> str:
    import re as _re
    found = _re.findall(r"\d+", str(ref or ""))
    return found[-1] if found else ""


def mark_source_conflicts(fragments, candidates) -> tuple[tuple, tuple]:
    """Пометить фрагменты, чьи источники противоречат (UR-13.5/§7 R1).

    Источник статуса — существующий provenance retrieval-контракта
    (`contradiction_status`/`verification`), второй детектор не вводится.
    Возврат: ``(fragments, conflicts)``."""
    by_digits: dict[str, str] = {}
    for cand in candidates or ():
        status = str(getattr(cand, "contradiction_status", "") or "")
        verification = str(getattr(cand, "verification", "") or "")
        if status in ("conflicting", "disputed") or verification in (
                "contradicts", "conflicting"):
            digits = _ref_digits(getattr(cand, "id", "") or "")
            if digits:
                by_digits[digits] = status or verification or "conflicting"
    if not by_digits:
        return tuple(fragments or ()), ()
    items: list = []
    conflicts: list[dict] = []
    for frag in fragments or ():
        status = by_digits.get(_ref_digits(frag.source_id))
        if status is None:
            items.append(frag)
            continue
        items.append(_replace_fragment(
            frag, authority=AUTHORITY_BACKGROUND,
            note=(f"источник помечен как {status} (есть противоречащая версия)"
                  if not frag.note else
                  f"{frag.note}; источник: {status}")))
        conflicts.append({"source_id": frag.source_id, "status": status})
    return tuple(items), tuple(conflicts)


def _replace_fragment(fragment: ContextFragment, **changes) -> ContextFragment:
    return _dc_replace(fragment, **changes)


# ── Overflow: дробление P0 без тихой потери середины/конца (UR-10.1) ────────

def split_overflow_fragments(fragment: ContextFragment, max_tokens: int, *,
                             measure=count_tokens) -> tuple:
    """Разбить длинный P0-фрагмент на связанные части со ссылкой на источник.

    Никакого ``text[:N]``: текст делится по словам/переносам на части ≤
    ``max_tokens``; конкатенация частей восстанавливает исходник (потерь нет).
    Каждая часть сохраняет ``source_id`` (реальный источник) и индексы
    ``part_index/part_total`` — потребитель может собрать сводный вход/повтор.
    """
    text = str(fragment.text or "")
    limit = int(max_tokens or 0)
    if limit <= 0 or not text:
        return (fragment,)
    if measure(text) <= limit:
        return (fragment,)
    import re as _re
    atoms = _re.findall(r"\S+\s*", text) or [text]
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for atom in atoms:
        cost = measure(atom)
        if cost > limit:
            # Экстремально длинный атом (без пробелов): обычный предел сети,
            # не смысловая отсечка — режем и его, но без потери символов.
            step = max(1, limit * 3)
            for start in range(0, len(atom), step):
                chunk = atom[start:start + step]
                if current:
                    parts.append("".join(current))
                    current, current_tokens = [], 0
                parts.append(chunk)
            continue
        if current and current_tokens + cost > limit:
            parts.append("".join(current))
            current, current_tokens = [], 0
        current.append(atom)
        current_tokens += cost
    if current:
        parts.append("".join(current))
    total = max(1, len(parts))
    return tuple(
        _replace_fragment(fragment, text=part, part_index=index + 1,
                          part_total=total)
        for index, part in enumerate(parts))


def compress_fragment_with_ref(fragment: ContextFragment, max_tokens: int, *,
                               measure=count_tokens) -> ContextFragment:
    """Сжатие длинного релевантного фрагмента СО ССЫЛКОЙ на оригинал.

    Только после того, как нерелевантное/вторичные конспекты/менее важные
    реплики уже сняты (UR-11.5). Сохраняется голова целыми словами и явная
    пометка, где взять полный текст."""
    text = str(fragment.text or "")
    limit = int(max_tokens or 0)
    if limit <= 0 or not text or measure(text) <= limit:
        return fragment
    kept: list[str] = []
    total = 0
    for atom in (text.split(" ")):
        cost = measure(atom + " ")
        if kept and total + cost > max(1, limit - 24):
            break
        kept.append(atom)
        total += cost
    marker = f" …[сокращено по бюджету; полный текст: {fragment.source_id}]"
    note = (f"{fragment.note}; сокращено по бюджету" if fragment.note
            else "сокращено по бюджету; полный текст по ссылке")
    return _replace_fragment(fragment, text=" ".join(kept) + marker, note=note)


# ── Единственная аллокация фрагментов ───────────────────────────────────────

def _count_by(items) -> dict:
    counts: dict[str, int] = {}
    for item in items or ():
        key = item.kind if isinstance(item, ContextFragment) else str(item)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _tokens_by(items, measure=count_tokens) -> dict:
    counts: dict[str, int] = {}
    for item in items or ():
        counts[item.kind] = counts.get(item.kind, 0) + item.tokens(measure)
    return counts


def allocate_selection(selection: ContextSelection,
                       budget_tokens: int,
                       *, measure=count_tokens) -> ContextSelection:
    """Единственное место усечения контекста (UR-11).

    Правила: «всё влезает — не режем» (§16); при нехватке — сначала
    нерелевантный фон (P3), затем вторичные конспекты/слабые выводы, затем
    менее важные реплики, и только потом сжатие длинных релевантных
    материалов со ссылкой на оригинал; P0 (вопрос/reply-parent/правка) не
    режется — при физическом переполнении дробится на части.
    """
    budget = int(budget_tokens or 0)
    ordered = list(selection.fragments())
    provenance = selection.provenance
    raw_total = sum(f.tokens(measure) for f in ordered)
    base = _replace_fragment_prov(
        provenance, budget_tokens=budget, raw_tokens=raw_total,
        selected_tokens=raw_total, selected_counts=_count_by(ordered))
    if budget <= 0 or raw_total <= budget:
        included = _replace_fragment_prov(
            base, included_counts=_count_by(ordered),
            included_tokens=raw_total, dropped=(), overflow=False)
        return _rebuild_selection(selection, ordered, included)

    dropped: list[dict] = []
    included = list(ordered)
    total = raw_total

    def _drop(predicate, reason: str) -> None:
        nonlocal included, total
        for frag in sorted([f for f in included if predicate(f)],
                           key=lambda f: (int(f.timestamp_utc or 0),
                                          f.source_id)):
            if total <= budget:
                return
            cost = frag.tokens(measure)
            included.remove(frag)
            total -= cost
            dropped.append({"source_id": frag.source_id, "kind": frag.kind,
                            "role": frag.role, "reason_code": reason,
                            "tokens": cost})

    # 1) нерелевантный фон (P3) — первым.
    _drop(lambda f: f.priority >= P3, "irrelevant_background")
    # 2) вторичные конспекты/выводы модели (P2, background authority) — от
    #    старых к новым.
    _drop(lambda f: f.priority == P2
          and f.authority == AUTHORITY_BACKGROUND, "secondary_summary")
    # 3) менее важные реплики памяти (P2, после summary).
    _drop(lambda f: f.priority == P2, "low_value_memory")

    # 4) сжатие длинных релевантных материалов со ссылкой (P1/P2), от самых
    #    длинных; P0 не сжимаем.
    guard = 0
    while total > budget and guard < 24:
        guard += 1
        candidates = [f for f in included
                      if f.priority > P0 and f.tokens(measure) > 48]
        if not candidates:
            break
        victim = max(candidates, key=lambda f: f.tokens(measure))
        target_tokens = max(32, victim.tokens(measure) // 2)
        compressed = compress_fragment_with_ref(victim, target_tokens,
                                                measure=measure)
        gained = victim.tokens(measure) - compressed.tokens(measure)
        if gained <= 0:
            break
        idx = included.index(victim)
        included[idx] = compressed
        total -= gained
        dropped.append({"source_id": victim.source_id, "kind": victim.kind,
                        "role": victim.role, "reason_code": "compressed",
                        "tokens": gained})

    # 5) физическое переполнение: P0 дробится на части со ссылками.
    overflow = total > budget
    overflow_parts: list[dict] = []
    if overflow:
        for role in (ROLE_CURRENT_QUESTION, ROLE_REPLY_PARENT):
            if total <= budget:
                break
            for frag in [f for f in included if f.role == role]:
                if total <= budget:
                    break
                share = max(24, int(budget * 0.6))
                parts = split_overflow_fragments(frag, share, measure=measure)
                if len(parts) <= 1:
                    continue
                idx = included.index(frag)
                included[idx] = parts[0]
                total = sum(f.tokens(measure) for f in included)
                for extra in parts[1:]:
                    if total + extra.tokens(measure) <= budget:
                        included.append(extra)
                        total += extra.tokens(measure)
                    else:
                        overflow_parts.append({
                            "source_id": extra.source_id,
                            "part": f"{extra.part_index}/{extra.part_total}",
                            "tokens": extra.tokens(measure),
                            "reason_code": "physical_overflow"})
                overflow = total > budget or bool(overflow_parts)

    # P0-фрагменты, не поместившиеся вовсе, отражаются честно (не молчим).
    kept_ids = {f.source_id for f in included}
    for frag in ordered:
        if frag.source_id in kept_ids or frag.priority > P0:
            continue
        overflow_parts.append({"source_id": frag.source_id,
                               "part": f"{frag.part_index}/{frag.part_total}",
                               "tokens": frag.tokens(measure),
                               "reason_code": "physical_overflow"})

    final_prov = _replace_fragment_prov(
        base, included_counts=_count_by(included),
        included_tokens=sum(f.tokens(measure) for f in included),
        dropped=tuple(dropped), overflow=bool(overflow or overflow_parts),
        overflow_parts=tuple(overflow_parts))
    ordered_final = [f for f in included]
    return _rebuild_selection(selection, ordered_final, final_prov)


def _replace_fragment_prov(provenance: SelectionProvenance,
                           **changes) -> SelectionProvenance:
    return _dc_replace(provenance, **changes)


def _rebuild_selection(selection: ContextSelection, fragments: list,
                       provenance: SelectionProvenance) -> ContextSelection:
    """Пересобрать selection из выживших фрагментов (порядок UR-09 сохранён)."""
    ordered = list(fragments)
    by_role: dict[str, list] = {}
    for frag in ordered:
        by_role.setdefault(frag.role, []).append(frag)
    current = (by_role.get(ROLE_CURRENT_QUESTION) or [None])[0]
    if current is None:
        current = selection.current_question
    reply_parent = (by_role.get(ROLE_REPLY_PARENT) or [None])[0]
    return ContextSelection(
        current_question=current,
        reply_parent=reply_parent,
        thread=tuple(by_role.get(ROLE_THREAD, ())),
        fresh_neighbours=tuple(by_role.get(ROLE_FRESH_NEIGHBOUR, ())),
        memory=tuple(by_role.get(ROLE_MEMORY, ())),
        self_outputs=tuple(by_role.get(ROLE_SELF_OUTPUT, ())),
        summary_map=selection.summary_map,
        evidence=selection.evidence,
        summary=tuple(by_role.get(ROLE_SUMMARY, ())),
        background=tuple(by_role.get(ROLE_BACKGROUND, ())),
        provenance=provenance)


# ── Сборка ContextSelection (порядок UR-09) ─────────────────────────────────

def _dedup_fragments(groups) -> tuple[list, int]:
    """Дедуп по source-идентичности с сохранением первого (приоритетного).

    Идентичность — реальный `tg_message_id` (одна и та же реплика может прийти
    из ветки, ledger и self-outputs) + номер части; иначе `source_id`.
    Дубликат не «исчезает»: недостающие метаданные (дата отправки, ревизия,
    correlation) переносятся в выживший фрагмент."""
    seen: dict = {}
    out: list = []
    duplicates = 0
    for group in groups:
        for frag in group or ():
            key = ((frag.tg_message_id, frag.part_index)
                   if frag.tg_message_id is not None
                   else (frag.source_id, frag.part_index))
            if key in seen:
                duplicates += 1
                index = seen[key]
                current = out[index]
                changes: dict = {}
                if not current.time_known and frag.time_known:
                    changes["time_known"] = True
                    changes["timestamp_utc"] = frag.timestamp_utc
                if not current.correlation_id and frag.correlation_id:
                    changes["correlation_id"] = frag.correlation_id
                if int(current.revision or 1) < int(frag.revision or 1):
                    changes["revision"] = frag.revision
                if not current.text and frag.text:
                    changes.update(text=frag.text, media_only=False)
                if changes:
                    out[index] = _replace_fragment(current, **changes)
                continue
            seen[key] = len(out)
            out.append(frag)
    return out, duplicates


def build_context_selection(
        *, current_text: str, chat_id: int | None = None,
        media_markers=(), speaker_uid: int | None = None,
        author_label: str = "", reply_to_tg: int | None = None,
        message_tg_id: int | None = None,
        timestamp_utc: int = 0,
        reply_parent: ContextFragment | None = None,
        thread=(), fresh_neighbours=(), memory=(), self_outputs=(),
        background=(), summary_map: SummaryMapRef | None = None,
        evidence=None, memory_candidates=(), budget_tokens: int = 0,
        raw_counts: dict | None = None) -> ContextSelection:
    """Собрать единый `ContextSelection` из готовых фрагментов (UR-09).

    Все данные уже типизированы существующими источниками (окно, thread_chain,
    ledger, retrieval, конспект). Здесь — порядок UR-09, дедуп по source_id,
    учёт правок/конфликтов, provenance и единственная аллокация.
    """
    markers = [str(m) for m in (media_markers or ()) if str(m or "").strip()]
    body = str(current_text or "")
    if markers:
        body = (body + "\n" + " ".join(markers)).strip() if body \
            else " ".join(markers)
    current = ContextFragment(
        kind=KIND_USER_STATEMENT,
        source_id=(f"msg:{int(message_tg_id)}" if message_tg_id is not None
                   else "msg:current"),
        timestamp_utc=int(timestamp_utc or 0),
        speaker_uid=speaker_uid,
        author_label=str(author_label or ""),
        text=body,
        reply_to=(f"tg:{int(reply_to_tg)}" if reply_to_tg is not None
                  else None),
        authority=AUTHORITY_PRIMARY,
        fresh=True,
        role=ROLE_CURRENT_QUESTION,
        tg_message_id=message_tg_id,
        reply_to_tg_id=reply_to_tg,
        time_known=bool(timestamp_utc),
        media_only=not str(current_text or "").strip(),
    )

    thread_items, thread_dups = _dedup_fragments([thread])
    neighbour_items, neighbour_dups = _dedup_fragments([fresh_neighbours])
    memory_items, memory_dups = _dedup_fragments([memory])
    self_items, self_dups = _dedup_fragments([self_outputs])
    background_items, background_dups = _dedup_fragments([background])
    memory_items, conflicts = mark_source_conflicts(memory_items,
                                                    memory_candidates)
    resolved_thread, corrections = detect_corrections(thread_items)

    summary_frag = (summary_map_fragment(summary_map)
                    if isinstance(summary_map, SummaryMapRef) else None)
    groups = ([current], [reply_parent] if reply_parent is not None else [],
              resolved_thread, neighbour_items, memory_items, self_items,
              [summary_frag] if summary_frag is not None else [],
              background_items)
    ordered, dups = _dedup_fragments(groups)
    raw = dict(raw_counts or {})
    if not raw:
        raw = _count_by(ordered)
    else:
        for kind, value in _count_by(ordered).items():
            raw[kind] = max(int(raw.get(kind, 0) or 0), value)
    provenance = SelectionProvenance(
        budget_tokens=int(budget_tokens or 0),
        raw_counts=raw,
        selected_counts=_count_by(ordered),
        raw_tokens=sum(f.tokens() for f in ordered),
        selected_tokens=sum(f.tokens() for f in ordered),
        memory_found=bool(memory_items) or bool(summary_frag),
        corrections=corrections,
        conflicts=conflicts,
    )
    # Собираем выборку из УЖЕ дедуплицированного списка (одна и та же реплика
    # может прийти из ветки, ledger и self-outputs — она остаётся один раз).
    duplicated = int(dups + thread_dups + neighbour_dups + memory_dups
                     + self_dups + background_dups)
    if duplicated:
        provenance = _replace_fragment_prov(
            provenance,
            dropped=tuple(provenance.dropped)
            + ({"reason_code": "duplicate_source", "count": duplicated},))
    base = ContextSelection(
        current_question=current,
        reply_parent=reply_parent,
        summary_map=summary_map,
        evidence=evidence,
        provenance=provenance,
    )
    selection = _rebuild_selection(base, ordered, provenance)
    return allocate_selection(selection, budget_tokens)


# ═══════════════════════════════════════════════════════════════════════════
# Коллекторы: превращают СУЩЕСТВУЮЩИЕ источники в типизированные фрагменты.
# Новых хранилищ/индексов/эмбеддингов не создаётся (UR-13/UR-23): окно,
# thread_chain, FTS/vector retrieval и durable ledger `mca_bot_outputs`.
# ═══════════════════════════════════════════════════════════════════════════

def collect_window_fragments(rows, *, working_window_messages: int = 20,
                             aliases=None, bot_user_id=None,
                             now_ts: int = 0,
                             fresh_window_seconds: int = 0):
    """Окно кандидатов → (свежие соседи P1, остальной фон P3).

    `get_window_messages` остаётся быстрым КАНДИДАТНЫМ хвостом (UR-09): его
    лимит по строкам — не информационный потолок модели. Свежие соседи темы
    (включая недавний ответ бота как факт диалога) — P1; всё прочее окно —
    фон P3, который allocator снимает первым."""
    content = [row for row in (rows or ()) if str(_row_value(row, "text") or
                                                "").strip()]
    try:
        keep = max(0, int(working_window_messages or 0))
    except (TypeError, ValueError):
        keep = 0
    fresh_rows = content[-keep:] if keep else []
    background_rows = content[:-keep] if keep else list(content)
    fresh = tuple(
        row_to_fragment(row, role=ROLE_FRESH_NEIGHBOUR, aliases=aliases,
                        bot_user_id=bot_user_id, fresh=True, now_ts=now_ts,
                        fresh_window_seconds=fresh_window_seconds)
        for row in fresh_rows)
    background = tuple(
        row_to_fragment(row, role=ROLE_BACKGROUND, aliases=aliases,
                        bot_user_id=bot_user_id, fresh=False, now_ts=now_ts,
                        fresh_window_seconds=fresh_window_seconds)
        for row in background_rows)
    return fresh, background


async def collect_memory_fragments(db, *, chat_id: int, candidates,
                                   aliases=None, bot_user_id=None,
                                   neighbours_before: int = 2,
                                   neighbours_after: int = 2,
                                   max_fragments: int = 10,
                                   role: str = ROLE_MEMORY):
    """Кандидаты retrieval → фрагменты с РЕАЛЬНЫМИ сообщениями и соседями.

    UR-13.3: на вопрос о прошлой ситуации модель видит слова участника с
    идентификаторами, а не короткий вывод. Кандидат-сообщение разворачивается
    через существующий `db.get_messages_around`; факты/эпизоды без дословной
    реплики подаются как `summary_inference` с явной пометкой (не выдаются за
    исходные слова). Возврат: ``(fragments, raw_count)``."""
    fragments: list = []
    raw = 0
    seen_tg: set = set()
    for cand in candidates or ():
        if len(fragments) >= max(1, int(max_fragments or 1)):
            break
        raw += 1
        entity_type = str(getattr(cand, "entity_type", "") or "")
        if entity_type == "message":
            tg = _ref_digits(getattr(cand, "id", "") or "")
            if not tg:
                continue
            try:
                tg_int = int(tg)
            except ValueError:
                continue
            if tg_int in seen_tg:
                continue
            try:
                rows = await db.get_messages_around(
                    chat_id, tg_int, before=int(neighbours_before or 0),
                    after=int(neighbours_after or 0))
            except Exception:      # fail-open: канал уже дал кандидата
                logger.debug("composer: memory rows read failed | chat=%s",
                             chat_id, exc_info=True)
                rows = []
            if not rows:
                continue
            hit = None
            for row in rows:
                if _row_value(row, "tg_message_id") == tg_int:
                    hit = row
                    break
            ordered = ([hit] if hit is not None else []) + \
                [row for row in rows if row is not hit]
            for row in ordered:
                row_tg = _row_value(row, "tg_message_id")
                if row_tg in seen_tg:
                    continue
                frag = row_to_fragment(row, role=role, aliases=aliases,
                                       bot_user_id=bot_user_id)
                if not frag.text:
                    continue            # media-only строка без текста
                seen_tg.add(row_tg)
                fragments.append(frag)
                if len(fragments) >= max(1, int(max_fragments or 1)):
                    break
            continue
        # graph_fact / episode: дословной реплики нет → вывод модели/факт,
        # поданный как низкодоверенный `summary_inference` с реальной ссылкой.
        preview = str(getattr(cand, "preview", "") or "").strip()
        if not preview:
            continue
        digits = _ref_digits(getattr(cand, "id", "") or "")
        source_id = (f"fact:{digits}" if entity_type == "graph_fact"
                     else f"episode:{getattr(cand, 'entity_id', '') or digits}")
        fragments.append(ContextFragment(
            kind=KIND_SUMMARY_INFERENCE,
            source_id=source_id,
            timestamp_utc=int(getattr(cand, "sent_at", 0) or 0),
            speaker_uid=getattr(cand, "author_id", None),
            author_label="память (вывод модели)",
            text=preview,
            authority=AUTHORITY_BACKGROUND,
            fresh=False,
            role=role,
            time_known=bool(getattr(cand, "sent_at", 0)),
            note="вывод/факт из памяти, не дословная реплика"))
    return tuple(fragments), raw


async def collect_self_output_fragments(db, *, chat_id: int, since_ts: int = 0,
                                        until_ts: int = 0, limit: int = 50,
                                        aliases=None, bot_user_id=None,
                                        role: str = ROLE_SELF_OUTPUT,
                                        exclude_tg=()):
    """Durable ledger → bot_statement фрагменты (UR-23, единый read-path).

    Реально доставленные собственные сообщения: `tg_message_id`,
    `sent_at_utc`, `reply_to`, `correlation_id`, ревизия; не стилевые якоря.
    Gate/DB/ошибка → честно пустой список (бот не притворяется помнящим)."""
    try:
        from services import bot_output_ledger as _ledger
    except Exception:          # pragma: no cover - защитная ветка
        return ()
    try:
        records = await _ledger.list_bot_output_history(
            db, chat_id, since_ts=since_ts, until_ts=until_ts,
            limit=limit)
    except Exception:
        logger.warning("composer: bot output history read failed | chat=%s",
                       chat_id, exc_info=True)
        return ()
    skip = set()
    for value in exclude_tg or ():
        try:
            skip.add(int(value))
        except (TypeError, ValueError):
            continue
    fragments: list = []
    for record in records or ():
        tg = record.get("tg_message_id")
        try:
            tg_int = int(tg) if tg not in (None, "", 0) else None
        except (TypeError, ValueError):
            tg_int = None
        if tg_int is not None and tg_int in skip:
            continue
        fragments.append(ledger_record_to_fragment(
            record, role=role, aliases=aliases, bot_user_id=bot_user_id))
    return tuple(fragments)


__all__ = [
    "COMPOSER_POLICY_VERSION", "P0", "P1", "P2", "P3", "BLOCK_PRIORITY",
    "PIECE_KEEP", "CANONICAL_ORDER", "ContextPiece", "AllocationResult",
    "composer_on",
    "fresh_tail_min_messages", "middle_max_messages", "thread_walk_max",
    "episode_gap_seconds", "episode_max_messages", "episode_max_count",
    "allocate_budget", "truncate_piece_text", "truncate_lines_keep_end",
    "truncate_lines_keep_start", "compute_episode_span", "select_middle",
    "tail_floor_tokens",
    "WINDOW_SOURCE_MAP", "WINDOW_SOURCE_ENV", "WINDOW_SOURCE_FALLBACK",
    "DIRECT_METRIC_NAMES", "record_direct_metric",
    "direct_metrics_snapshot", "reset_direct_metrics",
    "record_diagnostics", "get_diagnostics", "reset_diagnostics",
    "emit_context_capacity", "emit_context_select", "emit_context_pressure",
    "emit_context_physical_overflow", "emit_context_tail_floor_clamped",
    "emit_direct_trigger",
    "emit_direct_silent_ack", "emit_direct_silent_ack_failed",
    "model_capacity",
    # UNIFIED-REPLY UR-C: ContextSelection (UR-09/10/11/13/23)
    "SELECTION_POLICY_VERSION", "FRAGMENT_KINDS",
    "KIND_USER_STATEMENT", "KIND_CHAT_EVENT", "KIND_BOT_STATEMENT",
    "KIND_SUMMARY_INFERENCE", "KIND_EXTERNAL_EVIDENCE",
    "AUTHORITY_PRIMARY", "AUTHORITY_SUPPORTING", "AUTHORITY_BACKGROUND",
    "ROLE_CURRENT_QUESTION", "ROLE_REPLY_PARENT", "ROLE_THREAD",
    "ROLE_FRESH_NEIGHBOUR", "ROLE_MEMORY", "ROLE_SELF_OUTPUT",
    "ROLE_SUMMARY", "ROLE_BACKGROUND", "ROLE_PRIORITY", "ROLE_ORDER",
    "fragment_kind", "fragment_priority", "authority_for_kind",
    "ContextFragment", "SummaryMapRef", "SelectionProvenance",
    "ContextSelection", "preview_text", "row_to_fragment",
    "chain_item_to_fragment", "ledger_record_to_fragment", "summary_map_ref",
    "summary_map_fragment", "detect_corrections", "mark_source_conflicts",
    "split_overflow_fragments", "compress_fragment_with_ref",
    "allocate_selection", "build_context_selection",
    "collect_window_fragments", "collect_memory_fragments",
    "collect_self_output_fragments",
]
