"""ASAP 8 F2 (ТЗ §3/§28.3; architecture §2) — единый execution input Summary:
один preparation path для prod / Summary Test (dry-run) / replay-debug.

Проблема (audit-summary §2, ТЗ §3.2): production строил immutable
``SummarySourceWindow`` → anchor-space L1/L2; dry-run делал
``build_test_rows`` + голый ``run_l1(...)`` БЕЗ окна → anchor_mode=False →
map-v1 контракт на raw ``message_id`` → ``TEST_L1_INVALID ·
unknown_message_id`` на реальном окне (623 сообщения, ~76.7s впустую).
§28.3: у теста больше нет отдельного preparation path.

Контракт (architecture §2.1):
``build_summary_execution_input(...) -> SummaryExecutionInput`` —
rows, immutable source_window, anchor map, budget L1/L2, focus_block,
длина, слоты L1/L2, детерминированный fingerprint.

Роли вызывающих:
  * prod (`summary_generator._run_hybrid_l2`): durable-окно создаётся как
    сейчас (``_establish_source_window``) и передаётся готовым
    (``source_window=``) — постоянное хранение окна не меняется;
  * dry-run (`summary_test_run`): ``mount_window=True`` — окно монтируется
    В ПАМЯТИ (тот же ``build_source_window``, 0 durable-записей);
  * replay/debug: ``source_window=source_window_from_row(row)``.

Чистый модуль подготовки: 0 LLM-вызовов, 0 публикаций, 0 записей в БД.
Тяжелые зависимости (clusterizer/l2_writer/budget) импортируются лениво —
OFF-путь генератора не тянет модули L2 (прецедент ленивых импортов).
Никогда не бросает: любой сбой резолва → fail-open поле ``None``/"" (тот
fail-open паттерн, что у ``_establish_source_window``/``resolve_l1_effective_budget``).

Fingerprint-инвариант (S5): ``fingerprint = sha256(run_id ∥ messages_json)``
(обрезка 16 hex). ``messages_json`` — каноническая сериализация окна
(фиксированный порядок ключей ``build_source_window``) ⇒ один fixture
(те же rows в том же порядке) + тот же run_id ⇒ байт-одинаковый fingerprint
и байт-одинаковый ``anchor_map.run_fingerprint`` в prod- и test-путях.

R17: наружу только числа/коды/хеши; текстов сообщений нет.
"""
from __future__ import annotations

import dataclasses
import hashlib

# Точка/разделитель сепарируются явным NUL — без коллизий конкатенации.
_FP_SEPARATOR = "\x00"
_FP_LENGTH = 16


@dataclasses.dataclass(frozen=True)
class SummaryExecutionInput:
    """Единый подготовленный вход стадий L1/L2 Summary (architecture §2.1).

    ``rows`` — те же строки окна, что уходят в ``run_l1``; ``source_window``
    — immutable ``SummarySourceWindow`` (durable у prod / in-memory у
    dry-run; ``None`` — окно недоступно, fail-open к v1-контуру);
    ``anchor_map`` — ``SourceAnchorMap`` поверх окна (учитывает kill-switch
    ``SUMMARY_SOURCE_ANCHORS_ENABLED``); ``budget_l1``/``budget_l2`` —
    ``(kind, limit, budget_mode)`` (паритет/метаданные; бюджет ОДНОГО
    запроса L1 внутри run_l1 резолвится как раньше — capacity-first ветка
    требует ``budget=None`` на входе); ``length`` — цели Hybrid-статьи;
    ``slot_l1``/``slot_l2`` — слоты; ``fingerprint`` — детерминированный
    хеш run_id + checksum(rows) ("" — окна нет).
    """

    rows: list
    source_window: object | None
    anchor_map: object | None
    budget_l1: tuple | None
    budget_l2: tuple | None
    focus_block: str
    length: dict | None
    slot_l1: object | None
    slot_l2: object | None
    fingerprint: str


def window_fingerprint(run_id, messages_json: str) -> str:
    """Детерминированный fingerprint окна: sha256(run_id ∥ messages_json).

    Один fixture (+ один run_id) ⇒ один fingerprint (S5); другой run_id
    или другой материал окна ⇒ другой fingerprint. Никогда не бросает."""
    try:
        material = f"{str(run_id or '')}{_FP_SEPARATOR}" \
                   f"{str(messages_json or '')}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[
            :_FP_LENGTH]
    except Exception:      # pragma: no cover - защитная ветка
        return ""


def build_focus_block(focus) -> str:
    """Epic 65 (pure): «/summary про X» → ``<focus>``-блок user-контента.

    Единственный владелец формулировки (переехал из
    ``summary_generator._apply_focus`` байт-в-байт, чтобы prod и dry-run
    не разъехались). Пустой/пробельный focus → ""."""
    if not focus or not str(focus).strip():
        return ""
    from services.summary_xml import escape_xml_text   # локально — без циклов
    safe = escape_xml_text(str(focus).strip()[:200])
    return ('<focus note="главная тема этой выжимки — подсвети в саммари всё, '
            'что касается неё; остальное кратко">' + safe + "</focus>\n\n")


def _l1_system_prompt(*, anchor_mode: bool) -> str:
    """Канонический system-промпт L1 для режима (тот же выбор, что в
    ``run_l1``) — нужен резолверу бюджета L1 (system tokens mandatory)."""
    try:
        from services.prompt_style_blocks import resolve_prompt
        from services.summary_l1_clusterizer import (
            PROMPT_PG_KEY,
            SUMMARY_L1_ANCHORS_SYSTEM_PROMPT,
            SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT,
        )
        return resolve_prompt(
            PROMPT_PG_KEY,
            SUMMARY_L1_ANCHORS_SYSTEM_PROMPT if anchor_mode
            else SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT)
    except Exception:      # pragma: no cover - fail-open (бюджет → None)
        return ""


async def build_summary_execution_input(
        *, chat_id, rows, correlation_id, focus=None,
        trigger_message_id=None, window_run_id=None, source_window=None,
        mount_window: bool = False) -> SummaryExecutionInput:
    """Единая подготовка входа Summary (prod/test/replay; ТЗ §3.3).

    ``source_window`` — готовое окно (prod durable / replay read-back);
    ``mount_window=True`` — окно монтируется в памяти из ``rows``
    (dry-run; **0 durable-записей** — хранит окно только prod-путь).
    Если окно не задано и монтирование не запрошено — ``source_window=None``
    (вызывающий владеет решением; fail-open к v1-контуру как в 2.58).

    ``trigger_message_id`` принимается по контракту сигнатуры (ТЗ §3.3);
    в preparation L1/L2 он не участвует — его потребитель (legacy-путь и
    доставка генератора) продолжает получать его от вызывающего напрямую.

    Никогда не бросает; поля сбоя → ``None``/"" (fail-open, тот же
    паттерн, что у существующих резолверов)."""
    from services.summary_source_anchors import anchors_enabled
    from services.summary_source_window import build_source_window

    run_id = str(window_run_id or correlation_id or "").strip()
    rows_list = list(rows or [])

    # ── Immutable окно: готовое / in-memory / None (без side-effects). ─────
    if source_window is not None:
        window = source_window
    elif mount_window:
        window = build_source_window(run_id, chat_id, rows_list)
    else:
        window = None

    # ── Anchor map: тот же резолв, что run_l1/_run_writer_source_stage;
    #    kill-switch anchors учитывается здесь (anchor_mode = окно + флаг).
    anchor_map = None
    if window is not None and anchors_enabled():
        try:
            from services.summary_l1_clusterizer import resolve_anchor_map
            anchor_map = resolve_anchor_map(window, run_id=run_id,
                                            chat_id=chat_id)
        except Exception:      # pragma: no cover - fail-open к v1
            anchor_map = None

    # ── Focus-блок (единая формулировка с prod). ───────────────────────────
    focus_block = build_focus_block(focus)

    # ── Слоты (env/hot; dedicated-флаг честный). ───────────────────────────
    slot_l1 = None
    try:
        from services.summary_l1_clusterizer import resolve_l1_slot
        slot_l1 = resolve_l1_slot()
    except Exception:      # pragma: no cover - fail-open
        slot_l1 = None
    slot_l2 = None
    try:
        from services.summary_l2_writer import resolve_l2_slot_safe
        slot_l2 = resolve_l2_slot_safe()
    except Exception:      # pragma: no cover - fail-open (L2SlotError → None)
        slot_l2 = None

    # ── Бюджет L2-пакета (та же точка, что была в вызовах). ────────────────
    budget_l2 = None
    try:
        from services.summary_budget_auto import resolve_l2_package_budget
        budget_l2 = await resolve_l2_package_budget()
    except Exception:      # pragma: no cover - fail-open
        budget_l2 = None

    # ── Бюджет L1 (паритет-метаданные того же резолвера; сами вызовы L1
    #    сохраняют budget=None — capacity-first ветка run_l1). ─────────────
    budget_l1 = None
    try:
        from services.summary_budget_auto import resolve_l1_effective_budget
        budget_l1 = await resolve_l1_effective_budget(
            _l1_system_prompt(anchor_mode=anchor_map is not None), slot_l1)
    except Exception:      # pragma: no cover - резолвер fail-closed сам
        budget_l1 = None

    # ── Цели Hybrid-статьи (per-chat слой, как у Writer). ──────────────────
    length = None
    try:
        from services.summary_l2_writer import _hybrid_length_for_chat
        length = await _hybrid_length_for_chat(chat_id)
    except Exception:      # pragma: no cover - fail-open
        length = None

    # ── Fingerprint (S5): run_id + checksum(rows) окна. ────────────────────
    fingerprint = ""
    if window is not None:
        fingerprint = window_fingerprint(run_id,
                                         getattr(window, "messages_json", ""))

    return SummaryExecutionInput(
        rows=rows_list,
        source_window=window,
        anchor_map=anchor_map,
        budget_l1=budget_l1,
        budget_l2=budget_l2,
        focus_block=focus_block,
        length=length,
        slot_l1=slot_l1,
        slot_l2=slot_l2,
        fingerprint=fingerprint)


__all__ = [
    "SummaryExecutionInput",
    "build_summary_execution_input",
    "build_focus_block",
    "window_fingerprint",
]
