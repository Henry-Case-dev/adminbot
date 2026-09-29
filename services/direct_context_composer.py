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
from dataclasses import dataclass, field

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
P2 = 2        # running summary (background); Global head; RAG; level-2; map; nostalgia; mood
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
    # P1
    "global_tail": P1,
    "thread": P1,
    # P2
    "global_head": P2,
    "rag": P2,
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
}

# Канонический порядок слотов materialize (порядок блоков payload НЕ меняется
# — совместимость с промптом «важное к концу»; D3). Отсутствующие блоки
# просто не занимают слот; позиции детерминированы kind'ом.
CANONICAL_ORDER: dict[str, int] = {
    "map": 0,
    "branch": 1,
    "episode": 2,
    "rag": 3,
    "global_head": 4,
    "global_middle": 5,
    "global_tail": 6,
    "thread": 7,
    "target": 8,
    "relations": 9,
    "protected": 10,
    "lore": 11,
    "nostalgia": 12,
    "mood": 13,
    "current": 14,
    "anchors": 15,
    "sandwich": 16,
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
]
