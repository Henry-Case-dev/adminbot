"""SOUL-1 (W2) — единый Prompt Composer: один владелец сборки речи.

Контракт: `plans/features/soul-1/design-composer-contract.md` (§2 API, §3
таксономия уровней, §4 каноническая точка инъекции Core, §5 приоритеты,
§8 регрессионные швы). Источник истины: `design-source-of-truth.md`.

Инварианты этого модуля
-----------------------
1. **Только сборка.** Композер не пишет в PG, не вызывает LLM, не шлёт
   сообщений: он принимает уже готовые значения (refs) и возвращает
   immutable ``PromptManifest`` (system/user + трасса слоёв).
2. **Никогда не бросает.** Ошибка любого источника → блок не рендерится,
   ``skip_reason`` в трассе + notable-событие; сборка продолжается
   (паритет fail-open существующих слоёв).
3. **Один блок — один владелец.** Текст блока рендерит его существующий
   владелец (канон канала, persona/SelfModel, mca_style_scope,
   mca_experience, response_extent). Композер владеет только порядком,
   учётом бюджета, провенансом и (единственной) инъекцией Core.
4. **``skip_reason`` — это и есть причина деградации.** Он заполняется,
   когда слой не отрендерен ИЛИ когда отрендерен деградировавший вариант
   (``source=legacy_persona``, ``verbilizer_modes_disabled``): тихой
   подмены без причины не существует (SOUL-15.7).
5. **Ничего лишнего в модель.** Бюджет аддитивных слоёв (Core/Expression/
   Humor/Few-Shot/Style-Hint) ограничен; вопрос пользователя, инструкция и
   tool-evidence не вытесняются никогда (``user_parts`` возвращаются
   байт-в-байт).
"""
from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence

from services import mca_gates

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# §3 — таксономия слоёв (порядок рендера == порядок приоритета)
# ═════════════════════════════════════════════════════════════════════════════

LAYER_CHANNEL_CONTRACT = "channel_contract"
LAYER_CORE = "core"
LAYER_IDENTITY = "identity"
LAYER_SELF_MODEL_TRAITS = "self_model_traits"
LAYER_CONTEXT_LESSONS = "context_lessons"
LAYER_RESPONSE_PLAN = "response_plan"
LAYER_EXPRESSION = "expression"
LAYER_HUMOR_CRAFT = "humor_craft"
LAYER_FEW_SHOT = "few_shot"
LAYER_STYLE_POLICY_HINT = "style_policy_hint"
LAYER_CHANNEL_OUTPUT = "channel_output"

LAYER_ORDER: tuple[str, ...] = (
    LAYER_CHANNEL_CONTRACT, LAYER_CORE, LAYER_IDENTITY,
    LAYER_SELF_MODEL_TRAITS, LAYER_CONTEXT_LESSONS, LAYER_RESPONSE_PLAN,
    LAYER_EXPRESSION, LAYER_HUMOR_CRAFT, LAYER_FEW_SHOT,
    LAYER_STYLE_POLICY_HINT, LAYER_CHANNEL_OUTPUT,
)
LAYERS = frozenset(LAYER_ORDER)

# Владельцы блоков (закрытый набор, §3: «Один блок — один владелец»).
OWNERS = frozenset({
    "core", "persona", "self_model", "l1", "experience", "library",
    "style_policy", "channel", "legacy_canon",
})

# Провенанс значения (откуда эффективное значение взялось).
SOURCES = frozenset({
    "global", "chat", "participant", "topic", "default", "code", "migrated",
    "legacy_mode", "legacy_persona",
})

# Закрытый набор причин деградации/пропуска (§2 LayerTrace.
# skip_reason + W2-расширения для честных OFF-веток).
SKIP_REASONS = frozenset({
    "",
    # channel
    "channel_contract_missing", "channel_output_not_required",
    # core
    "core_absent", "core_disabled", "core_read_error",
    # identity / SelfModel
    "identity_absent", "identity_read_error", "persona_disabled",
    "character_layers_disabled", "self_model_absent",
    "self_model_folded_into_identity",
    # context_lessons
    "lessons_absent", "lessons_unavailable", "style_requests_absent",
    "style_scope_disabled", "speech_absent", "character_speech_disabled",
    # response plan
    "response_plan_absent", "response_plan_disabled",
    "verbilizer_modes_disabled",
    # expression / humor / few-shot / style policy
    "expression_absent", "expression_disabled",
    "expression_examples_absent", "expression_examples_disabled",
    # ADD-EXP (BLOCK-1): строки режима есть, но владелец их не утверждал —
    # в runtime не идут, причина видна в манифесте/событии.
    "not_owner_approved",
    "humor_no_strategy", "humor_disabled",
    # SPEECH-SIMPLIFY §2.2: короткая HUMOR уже вошла в базовый речевой блок;
    # отдельный слой приёма не дублирует её в payload.
    "humor_folded_into_speech_base",
    "samples_absent", "samples_disabled",
    "style_policy_absent", "style_policy_disabled", "style_policy_unavailable",
    "style_policy_read_error",
    # QUOTA-REMOVAL (ADDENDUM #3 §2.7): `budget_excluded` больше не существует —
    # искусственного бюджета инструкций нет; остаются только смысловые причины.
    "compose_error",
    "profile:machine_stage", "profile:editorial_eligibility",
    "profile:internal_silent",
})

# §2.2 — закрытый набор профилей («что вообще можно подключить»).
PROFILE_MACHINE_JSON = "machine_json"
PROFILE_SPEECH_PLAIN = "speech_plain"
PROFILE_SPEECH_RICH = "speech_rich"
PROFILE_EDITORIAL_REPORT = "editorial_report"
PROFILE_CHANNEL_TEXT_ONLY = "channel_text_only"
PROFILE_INTERNAL_SILENT = "internal_silent"

PROFILES = frozenset({
    PROFILE_MACHINE_JSON, PROFILE_SPEECH_PLAIN, PROFILE_SPEECH_RICH,
    PROFILE_EDITORIAL_REPORT, PROFILE_CHANNEL_TEXT_ONLY,
    PROFILE_INTERNAL_SILENT,
})

# Речевые профили: получают Core/Identity/Humor/Examples/Style.
_SPEECH_PROFILES = frozenset({
    PROFILE_SPEECH_PLAIN, PROFILE_SPEECH_RICH, PROFILE_CHANNEL_TEXT_ONLY,
    PROFILE_EDITORIAL_REPORT,
})
# Профили, которым РАЗРЕШЁН Core. `editorial_report` — только по явной
# редакционной eligibility владельца (owner-decisions d, ещё не выдано →
# `profile:editorial_eligibility`); `internal_silent` — по owner-decisions (b).
_CORE_PROFILES = frozenset({
    PROFILE_SPEECH_PLAIN, PROFILE_SPEECH_RICH, PROFILE_CHANNEL_TEXT_ONLY,
})

# QUOTA-REMOVAL (ADDENDUM #3 §2.7): кортеж `_BUDGET_LAYERS` удалён вместе с
# аддитивным бюджетом — приоритет слоёв задаёт порядок сборки, а не квота.

# Дефолтные причины «слоя нет» (когда ref не передан вовсе).
_ABSENT_REASON = {
    LAYER_CHANNEL_CONTRACT: "channel_contract_missing",
    LAYER_CORE: "core_absent",
    LAYER_IDENTITY: "identity_absent",
    LAYER_SELF_MODEL_TRAITS: "self_model_folded_into_identity",
    LAYER_CONTEXT_LESSONS: "lessons_absent",
    LAYER_RESPONSE_PLAN: "response_plan_absent",
    LAYER_EXPRESSION: "expression_absent",
    LAYER_HUMOR_CRAFT: "humor_no_strategy",
    LAYER_FEW_SHOT: "samples_absent",
    LAYER_STYLE_POLICY_HINT: "style_policy_absent",
    LAYER_CHANNEL_OUTPUT: "channel_output_not_required",
}

_PROFILE_REASON = {
    PROFILE_MACHINE_JSON: "profile:machine_stage",
    PROFILE_EDITORIAL_REPORT: "profile:editorial_eligibility",
    PROFILE_INTERNAL_SILENT: "profile:internal_silent",
}

# Причины-деградации/сбои для notable-событий (outcome/level/reason_code).
_OFF_REASONS = frozenset({
    "core_disabled", "persona_disabled", "character_layers_disabled",
    "style_policy_disabled", "samples_disabled", "humor_disabled",
    "expression_disabled", "expression_examples_disabled",
    "response_plan_disabled",
    "verbilizer_modes_disabled", "style_scope_disabled",
    "character_speech_disabled",
})
_ERROR_REASONS = frozenset({
    "core_read_error", "identity_read_error", "style_policy_read_error",
    "style_policy_unavailable", "lessons_unavailable",
})

#: Устаревшие служебные метки SOUL-* (INS-CONFLICT): в payload модели их быть
#: не должно. Проверка фактическая — по тексту отрендеренных блоков.
_SOUL_LABEL_RE = re.compile(r"SOUL-\d+(?:\.\d+)*")

#: Человеческие подписи слоёв для Inspector (INS-HIERARCHY). Ключ — слой из
#: закрытого набора ``LAYERS``; неизвестный слой показывается как есть.
LAYER_LABELS: Mapping[str, str] = {
    LAYER_CHANNEL_CONTRACT: "Контракт канала (L2)",
    LAYER_CORE: "Характер (Core)",
    LAYER_IDENTITY: "Личность и манера",
    LAYER_SELF_MODEL_TRAITS: "Самоощущение",
    LAYER_CONTEXT_LESSONS: "Контекст: уроки и правила",
    LAYER_RESPONSE_PLAN: "План ответа",
    LAYER_EXPRESSION: "Выражение (настройки речи)",
    LAYER_HUMOR_CRAFT: "Приём юмора",
    LAYER_FEW_SHOT: "Примеры (few shot)",
    LAYER_STYLE_POLICY_HINT: "Стиль письма",
    LAYER_CHANNEL_OUTPUT: "Формат вывода",
}

#: INS-SKIPREASON: доступный русский вместо машинного кода в основном тексте.
#: Код остаётся в диагностике (``title``/``reason_code``), не как основной
#: текст для владельца. Покрывает весь ``SKIP_REASONS``.
SKIP_REASON_LABELS: Mapping[str, str] = {
    "": "",
    "channel_contract_missing":
        "База канала не передана — этот блок не вошёл в запрос.",
    "channel_output_not_required":
        "Отдельный форматный блок этому этапу не нужен.",
    "core_absent":
        "Характер (Core) не передан — слой пуст, модель его не получила.",
    "core_disabled":
        "Характер (Core) выключен настройкой — слой не отправлен.",
    "core_read_error":
        "Характер не удалось прочитать — слой честно пропущен.",
    "identity_absent": "Описание личности не задано — слой пуст.",
    "identity_read_error":
        "Описание личности не удалось прочитать — слой пропущен.",
    "persona_disabled": "Личность (персона) выключена настройкой.",
    "character_layers_disabled":
        "Слои характера выключены — используется прежний режим.",
    "self_model_absent":
        "Самоощущение не задано, отдельного блока нет.",
    "self_model_folded_into_identity":
        "Самоощущение уже вошло в описание личности — отдельный блок не нужен.",
    "lessons_absent": "Уроков и правил для этого чата нет — блок пуст.",
    "lessons_unavailable":
        "Уроки опыта недоступны (хранилище) — слой честно пропущен.",
    "style_requests_absent":
        "В сообщении нет просьб о стиле — отдельный блок не нужен.",
    "style_scope_disabled":
        "Правила «в этом чате» выключены — слой не отправлен.",
    "speech_absent":
        "Настройки речи пусты — отдельного блока нет.",
    "character_speech_disabled":
        "Настройки речи выключены — слой не отправлен.",
    "response_plan_absent":
        "План ответа не сформирован — модель получила запрос без плана.",
    "response_plan_disabled":
        "План ответа выключен — модель получила запрос без плана.",
    "verbilizer_modes_disabled":
        "Умные режимы речевого слоя выключены — использована прежняя база.",
    "expression_absent": "Параметры манеры речи не заданы — блок пуст.",
    "expression_disabled":
        "Параметры манеры речи выключены — слой не отправлен.",
    "expression_examples_absent":
        "Примеры не выбраны: нет подходящих подтверждённых примеров.",
    "expression_examples_disabled":
        "Библиотека примеров выключена — примеры не отправлены.",
    "not_owner_approved":
        "Владелец не утвердил этот текст — в запрос он не идёт.",
    "humor_no_strategy":
        "Приём юмора на этот ход не выбран — отдельного блока нет.",
    "humor_disabled":
        "Приёмы юмора выключены — слой не отправлен.",
    "samples_absent":
        "Примеры не выбраны: нет подходящих подтверждённых примеров.",
    "samples_disabled":
        "Библиотека примеров выключена — примеры не отправлены.",
    "style_policy_absent":
        "Активных правил стиля письма нет — блок пуст.",
    "style_policy_disabled":
        "Правила стиля письма выключены — слой не отправлен.",
    "style_policy_unavailable":
        "Правила стиля письма недоступны — слой честно пропущен.",
    "style_policy_read_error":
        "Правила стиля письма не удалось прочитать — слой пропущен.",
    "compose_error":
        "Сборка слоя не удалась — отправлена только база канала.",
    "profile:machine_stage":
        "Машинный этап: личность и стиль к этому вызову не относятся.",
    "profile:editorial_eligibility":
        "Редакционный профиль ждёт разрешения владельца — Core не подключён.",
    "profile:internal_silent":
        "Служебный молчаливый профиль: ответ в чат не формируется.",
}


def layer_label(layer: Any) -> str:
    """Человеческое имя слоя (INS-HIERARCHY); неизвестный — как есть."""
    code = str(layer or "")
    return LAYER_LABELS.get(code, code or "—")


def skip_reason_label(code: Any) -> str:
    """Человеческая причина пропуска (INS-SKIPREASON); код — не текст."""
    key = str(code or "")
    if not key:
        return ""
    known = SKIP_REASON_LABELS.get(key)
    if known:
        return known
    # Незнакомый код не выдумываем: честно показываем его как технический.
    return "Слой пропущен (техническая причина: %s)." % key

# ═════════════════════════════════════════════════════════════════════════════
# Оценка и хеши
# ═════════════════════════════════════════════════════════════════════════════


def estimate_tokens(text: str) -> int:
    """Тот же оценщик, что в Experience (``mca_experience._estimate_tokens``).

    4 символа ≈ токен; отдельного счётчика композер не заводит.
    """
    return max(1, (len(str(text or "")) + 3) // 4)


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def _sha16(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def identity_revision_from_text(text: str) -> str:
    """Ревизия рендера личности (меняется вместе с текстом персоны)."""
    return _sha16(text)


def _norm_for_compare(text: str) -> str:
    """Нормализация для детекта дубля owner-характера (SOUL-03.6)."""
    out: list[str] = []
    for ch in str(text or "").casefold():
        if ch.isalnum() or ch in " ":
            out.append(ch)
        elif ch in "\n\t":
            out.append(" ")
    return " ".join("".join(out).split())


# ═════════════════════════════════════════════════════════════════════════════
# Типизированный вход (§2 API)
# ═════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Block:
    """Готовый блок от своего владельца.

    Пустой ``text`` + непустой ``skip_reason`` — легальная трасса
    «блок выключен/недоступен»: манифест покажет причину, текст в модель
    не поедет.
    """

    block_id: str
    text: str = ""
    owner: str = ""
    source: str = "code"
    revision: str = ""
    enabled: bool = True
    skip_reason: str = ""


@dataclass(frozen=True)
class CoreRef:
    """Personality Core (§2.1) — отдельный аддитивный слой."""

    text: str = ""
    revision: str = ""
    source: str = "global"
    document_revision: str = ""
    detail_level: str = "compact"
    compact_words: int = 0
    origin: str = "owner_edit"
    enabled: bool = True
    skip_reason: str = ""
    #: Почему действует именно эта редакция (закрытый набор
    #: ``prompt_registry.CORE_DETAIL_REASONS``): выбор владельца, заводской
    #: дефолт или бюджет контекста. Видно в манифесте слоя ``core``.
    detail_reason: str = ""


@dataclass(frozen=True)
class IdentityRef:
    """Имя/биография/устойчивые отношения/owner style (слой 3)."""

    text: str = ""
    revision: str = ""
    source: str = "chat"
    skipped: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class SelfModelRef:
    """Проверенные изменяемые черты (слой 4), если рендерятся отдельно."""

    text: str = ""
    revision: str = ""
    source: str = "chat"


@dataclass(frozen=True)
class PlanRef:
    """ResponsePlan/L1Plan: extent/structure/tone/delivery_hint/comic_strategy.

    ``extent`` — значение как есть (например ``one_word``): композер
    переносит его строкой и НЕ подменяет алиасом (W3 доводит до payload).
    """

    text: str = ""
    revision: str = ""
    source: str = "l1"
    extent: str = ""
    structure: str = ""
    tone: str = ""
    comic_strategy: str = ""
    enabled: bool = True
    skip_reason: str = ""


@dataclass(frozen=True)
class StylePolicyRef:
    """Снимок effective_style_policy (W3) — в W2 только hint + версия."""

    hint: str = ""
    revision: str = ""
    source: str = "default"
    rule_count: int = 0
    soft_count: int = 0
    enabled: bool = True
    skip_reason: str = ""
    #: ASAP3 §1.5: фактический состав hint (всего/включено/исключено) и
    #: действующий лимит (0 = без ограничения).
    hint_total: int = 0
    hint_included: int = 0
    hint_excluded: tuple = ()
    hint_limits: tuple = ()
    hint_limited_by: str = ""
    hint_truncated: bool = False


@dataclass(frozen=True)
class ExpressionSettings:
    """Owner-контролы интенсивности/формы собственной речи (soft).

    ADD-EXP: ``mode`` — канонический effective-режим ``profanity``
    (``inherit``/``off``/``occasional``/``frequent``; код, не текст) для
    диагностики/трасс; текст слоя рендерит единственный владелец
    ``services.mca_expression`` (preview == бой).
    """

    text: str = ""
    revision: str = ""
    source: str = "global"
    label: str = ""
    enabled: bool = True
    skip_reason: str = ""
    mode: str = ""


@dataclass(frozen=True)
class HumorStrategy:
    """Приём юмора (SOUL-06/W4): не личность, 0 доп. LLM-вызовов."""

    text: str = ""
    technique: str = ""
    revision: str = ""
    source: str = "library"
    enabled: bool = True
    skip_reason: str = ""


@dataclass(frozen=True)
class LessonRef:
    """Один блок проверенных уроков (owner mca_experience)."""

    block_id: str = "verified_lessons"
    text: str = ""
    revision: str = ""
    source: str = "chat"
    lesson_ids: tuple[int, ...] = ()
    enabled: bool = True
    skip_reason: str = ""


@dataclass(frozen=True)
class SampleRef:
    """Блок few-shot примеров (Sample Library, W4)."""

    block_id: str = "few_shot"
    text: str = ""
    revision: str = ""
    source: str = "global"
    library_version: str = ""
    technique: str = ""
    reason: str = ""
    enabled: bool = True
    skip_reason: str = ""


@dataclass(frozen=True)
class GateState:
    """Резолвнутые оси (env-emergency AND product-toggle; per-chat где можно)."""

    # ── новые оси SOUL-1/W2 (без дублей существующих рубильников) ──────────
    unified_composer_enabled: bool = False
    character_core_enabled: bool = True
    speech_style_policy_enabled: bool = True
    humor_library_enabled: bool = False
    humor_feedback_enabled: bool = False
    #: W4 (SOUL-06.7): ось ремесла юмора. OFF → слой приёмов не рендерится
    #: (`humor_disabled`), Core/Identity/Style/Samples не затронуты.
    humor_craft_enabled: bool = False
    #: ADD-EXP §3.3: своя env-ось few-shot набора регистра речи (kill-switch,
    #: default ON). OFF → блок `expression_examples` не рендерится
    #: (`expression_examples_disabled`); слой инструкции «Выражения» жив.
    expression_examples_enabled: bool = True
    # ── существующие оси (композер их уважает, не переопределяет) ──────────
    persona_enabled: bool = True
    character_layers_enabled: bool = True
    smart_verbalizer_modes_enabled: bool = True
    response_plan_enabled: bool = True

    def as_flags(self) -> dict[str, bool]:
        return dict(dataclasses.asdict(self))


@dataclass(frozen=True)
class PromptPlan:
    """Типизированный вход композера (закрытый набор профилей §2.2)."""

    profile: str = PROFILE_MACHINE_JSON
    writer: str = ""
    chat_id: int = 0
    channel: str = "plain"
    html_safe: bool = False
    run_id: str | None = None
    base_prompt: str = ""
    base_source: str = "default"
    include_mode_block: bool = True
    response_mode: str = ""
    core: CoreRef | None = None
    identity: IdentityRef | None = None
    self_model: SelfModelRef | None = None
    response_plan: PlanRef | None = None
    expression: ExpressionSettings | None = None
    #: ADD-EXP §3.2/§3.3: few-shot набор регистра речи (owner `core`, слой
    #: `few_shot`, ДО humor-примеров). Пусто → честная причина
    #: `expression_examples_absent` в манифесте.
    expression_examples: tuple[SampleRef, ...] = ()
    humor: HumorStrategy | None = None
    lessons: tuple[LessonRef, ...] = ()
    samples: tuple[SampleRef, ...] = ()
    style_policy: StylePolicyRef | None = None
    scoped_requests: tuple[Block, ...] = ()
    speech: Block | None = None
    user_parts: tuple[str, ...] = ()
    gates: GateState | None = None


@dataclass(frozen=True)
class LayerTrace:
    """Трасса одного блока (§2 LayerTrace)."""

    layer: str
    block_id: str
    owner: str = ""
    source: str = "code"
    revision: str = ""
    chars: int = 0
    tokens: int = 0
    rendered: bool = False
    skip_reason: str = ""
    conflict: str = ""
    #: Уточнение провенанса блока (без текста промпта): например выбор
    #: редакции Core (`level=… reason=… origin=… doc=…`).
    detail: str = ""
    #: ТОЧНЫЙ текст включённого блока (только ``rendered=True``). Живёт в
    #: манифесте in-memory (owner-debug, INS-HIERARCHY); в события/телеметрию
    #: НЕ попадает — ``manifest_for_events``/``render_effective_layers``
    #: собирают поля явно.
    text: str = ""


@dataclass(frozen=True)
class ConflictRecord:
    """Исход конфликта (закрытый набор §5) с провенансом."""

    conflict_id: str
    outcome: str
    layer: str
    block_id: str
    detail: str = ""
    provenance: str = ""


CONFLICT_OUTCOMES = frozenset({
    "keep_stronger", "exempted_protected", "repaired", "conflict_reported",
    "denied",
})


@dataclass(frozen=True)
class PromptManifest:
    """Результат сборки: immutable снимок хода."""

    system: str
    user_parts: tuple[str, ...] = ()
    layers: tuple[LayerTrace, ...] = ()
    versions: Mapping[str, str] = field(default_factory=dict)
    flags: Mapping[str, bool] = field(default_factory=dict)
    conflicts: tuple[ConflictRecord, ...] = ()
    manifest_id: str = ""
    profile: str = ""
    writer: str = ""
    chat_id: int = 0
    run_id: str | None = None
    tokens_total: int = 0


# ═════════════════════════════════════════════════════════════════════════════
# Резолв осей (никогда не бросает)
# ═════════════════════════════════════════════════════════════════════════════


def gates_from_config() -> GateState:
    """Глобальные/дефолтные оси (без per-chat). Никогда не бросает."""
    try:
        from services import hot_config as hot
        from services import response_extent as _extent
        from config.settings import settings

        return GateState(
            unified_composer_enabled=mca_gates.unified_composer_enabled(),
            character_core_enabled=mca_gates.character_core_enabled(),
            speech_style_policy_enabled=mca_gates.speech_style_policy_enabled(),
            humor_library_enabled=mca_gates.humor_library_enabled(),
            humor_feedback_enabled=mca_gates.humor_feedback_enabled(),
            humor_craft_enabled=mca_gates.humor_craft_enabled(),
            expression_examples_enabled=mca_gates.expression_examples_enabled(),
            persona_enabled=bool(hot.get("flags.persona_enabled",
                                        getattr(settings, "PERSONA_ENABLED",
                                                True))),
            character_layers_enabled=mca_gates.character_layers_enabled(),
            smart_verbalizer_modes_enabled=bool(getattr(
                settings, "SMART_VERBALIZER_MODES_ENABLED", True)),
            response_plan_enabled=bool(_extent.response_plan_enabled()),
        )
    except Exception:          # pragma: no cover — защитная ветка
        logger.warning("[composer] gates resolve failed — strict defaults",
                       exc_info=True)
        return GateState(unified_composer_enabled=False)


async def resolve_gates(chat_id: int) -> GateState:
    """Per-chat резолв новых осей (env AND catalog; §6).

    Читает те же источники, что остальной рантайм: ``chat_params``
    (overrides → hot → default) и ``hot_config``. Никогда не бросает;
    при выключенной env-оси работы не делает вообще (паритет/нулевая цена).
    """
    if not mca_gates.unified_composer_env_enabled():
        # Единственное чтение OFF-пути: env-ось. Ни hot, ни chat_params.
        return GateState(unified_composer_enabled=False)
    base = gates_from_config()
    try:
        from services.chat_params import get_chat_param as _cpg
    except Exception:          # pragma: no cover — защитная ветка
        return base
    out = base
    for name, pg_key in (
            ("unified_composer_enabled", "flags.unified_composer_enabled"),
            ("character_core_enabled", "flags.character_core_enabled"),
            ("speech_style_policy_enabled",
             "flags.speech_style_policy_enabled"),
            ("humor_library_enabled", "flags.humor_library_enabled"),
            ("humor_feedback_enabled", "flags.humor_feedback_enabled"),
            ("humor_craft_enabled", "flags.humor_craft_enabled")):
        default = bool(getattr(base, name))
        env_axis = mca_gates.w2_env_axis(
            mca_gates.W2_ENV_KEYS.get(name, ""), default)
        try:
            value = bool(await _cpg(chat_id, pg_key, default))
        except Exception:
            value = default
        out = replace(out, **{name: bool(env_axis and value)})
    return out


def composer_enabled_now(gates: GateState) -> bool:
    """Единая точка вопроса «композер включён?» для вызывающих.

    BLOCKER (review-w2 F1, машинно-проверяемый маркер в
    `plans/features/soul-1/w2-composer-report.md`): владелец НЕ включает
    `UNIFIED_COMPOSER_ENABLED` в проде, пока слайс-amendment не уберёт
    legacy speech-кастомы (`prompts.direct_chat_verbalizer_system_prompt` /
    `prompts.direct_chat_system_prompt`) из effective-слоя с предварительным
    backup (§7.2, SOUL-AMD.1.2/8.4). До этого включение рендерит старый
    кастом слоем `channel_contract` в противоречии с уточнением владельца.
    """
    try:
        return bool(gates.unified_composer_enabled)
    except Exception:          # pragma: no cover
        return False


# ═════════════════════════════════════════════════════════════════════════════
# Доступ к документам сущностей (read-only; W2-аксессоры)
# ═════════════════════════════════════════════════════════════════════════════

CORE_KEY = "character.core"
#: Уровни подробности Core. Действующий уровень выбирает
#: ``prompt_registry.core_selection`` (владелец — реестр: там же закрытый набор
#: причин ``CORE_DETAIL_REASONS``); здесь оставлено как публичное имя контракта.
CORE_DETAIL_LEVELS = frozenset({"compact", "full"})


def _as_document(raw: Any) -> dict | None:
    """JSON-документ из ``bot_settings``/``chat_params`` (dict или jsonb-str)."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            parsed = json.loads(raw.decode("utf-8") if isinstance(
                raw, (bytes, bytearray)) else raw)
        except Exception:
            return None
        return dict(parsed) if isinstance(parsed, Mapping) else None
    return None


async def _chat_override(chat_id: int, key: str) -> Any:
    """Значение ТОЛЬКО chat-слоя (`chat_params.overrides`), без глобального.

    Резолвер рантайма (`chat_params.get_chat_param`) сливает chat→global, а
    для видимого источника нужен именно chat-слой — поэтому читаем
    `overrides` из того же кэша per-chat параметров (одна точка правды).
    """
    try:
        from services.chat_params import get_chat_params_cache
        cache = get_chat_params_cache()
        if cache is None:
            return None
        root = await cache.get_chat_params(chat_id)
        if not isinstance(root, Mapping):
            return None
        return (root.get("overrides") or {}).get(key)
    except Exception:
        return None


def _document_layers(raw_global: Any, raw_chat: Any) -> tuple[dict | None,
                                                             str]:
    """``(document, source)``: chat-переопределение → global → отсутствие."""
    chat_doc = _as_document(raw_chat)
    if chat_doc is not None:
        return chat_doc, "chat"
    glob_doc = _as_document(raw_global)
    if glob_doc is not None:
        return glob_doc, "global"
    return None, "default"


async def resolve_core_ref(chat_id: int) -> CoreRef:
    """Снимок Personality Core на ход (§2.1). Никогда не бросает.

    Документ владельца — ``character.core`` (chat → global). Если документа
    нет, действует ЗАВОДСКАЯ редакция зарегистрированного Core
    (``core.personality`` = полный авторский текст SOUL-02 /
    ``core.personality.compact`` = ручное сжатие, SOUL-AMD.1.1): Core больше
    не «отсутствует» — он виден как ``source="default"``, ``origin="factory"``
    с заводской ревизией ``fac:<sha12>``.

    Если конфигурационный слой недоступен (PG down), поведение прежнее:
    ``core_absent`` без выдуманной конфигурации — тот же инвариант, что у W1
    (кодовый fallback не подменяется на сборке) и OFF-паритет W2 не
    затрагивается.

    Выбор редакции (полная/компактная) и его причина детерминированы
    (``prompt_registry.core_selection``: документ владельца + заводские
    редакции + бюджет слоёв, без единого LLM-вызова) и видны в манифесте:
    слой ``core`` (``detail``) и ``versions["core_detail"]``.
    """
    try:
        from services import hot_config as hot
        raw_global = hot.get(CORE_KEY, None)
        layer_available = hot.get_config_cache() is not None
    except Exception:          # pragma: no cover — защитная ветка
        raw_global, layer_available = None, False
    raw_chat = None
    try:
        raw_chat = await _chat_override(chat_id, CORE_KEY)
    except Exception:          # pragma: no cover — защитная ветка
        raw_chat = None
    try:
        doc, source = _document_layers(raw_global, raw_chat)
    except Exception:
        logger.warning("[composer] core doc unreadable", exc_info=True)
        return CoreRef(skip_reason="core_read_error")
    if doc is None and not layer_available:
        # PG down: конфигурацию не выдумываем (прежнее честное состояние).
        return CoreRef(source="default", skip_reason="core_absent")
    try:
        from services import prompt_registry as _pr
        enabled = True if doc is None else bool(doc.get("enabled", True))
        selection = _pr.core_selection(doc, source=source)
        text = str(selection["text"] or "")
        present = bool(text.strip())
        skip_reason = ("core_disabled" if not enabled
                       else "" if present else "core_absent")
        return CoreRef(
            text=text,
            revision=str(selection["revision"]),
            source=source,
            document_revision=str(selection["document_revision"]),
            detail_level=str(selection["level"]),
            detail_reason=str(selection["reason"]),
            compact_words=int(selection["compact_words"]),
            origin=str(selection["origin"]),
            enabled=enabled,
            skip_reason=skip_reason)
    except Exception:
        logger.warning("[composer] core doc malformed", exc_info=True)
        return CoreRef(source=source, skip_reason="core_read_error")


async def resolve_expression_settings(chat_id: int) -> ExpressionSettings:
    """Снимок слоя «Выражение» на ход (ADD-EXP §1.6/§1.2). Никогда не бросает.

    Читает документ ``character.expression`` (chat override → global) теми же
    источниками, что остальной рантайм (``chat_params``/``hot_config``), и
    строит ``ExpressionSettings`` ЕДИНЫМ builder-ом
    ``services.mca_expression.build_expression_settings`` — preview и бой
    рендерят один и тот же текст (EXP-ACCEPT.PREVIEW).

    Per-control merge chat→global→factory: частичный chat-документ больше не
    «затирает» контролы из global. Если конфигурационный слой недоступен
    (PG down) — честный ``expression_absent`` без выдуманной конфигурации
    (тот же инвариант, что у ``resolve_core_ref``).
    """
    from services import mca_expression as _expr

    try:
        from services import hot_config as hot
        raw_global = hot.get(_expr.EXPRESSION_DOC_KEY, None)
        layer_available = hot.get_config_cache() is not None
    except Exception:          # pragma: no cover — защитная ветка
        raw_global, layer_available = None, False
    raw_chat = None
    try:
        raw_chat = await _chat_override(chat_id, _expr.EXPRESSION_DOC_KEY)
    except Exception:          # pragma: no cover — защитная ветка
        raw_chat = None
    if (not isinstance(raw_global, Mapping)
            and not isinstance(raw_chat, Mapping) and not layer_available):
        # PG down: конфигурацию не выдумываем (честная причина видна в
        # манифесте/событии, а не «слой молча отсутствует»).
        return ExpressionSettings(source="default",
                                  skip_reason="expression_absent")
    try:
        return _expr.build_expression_settings(raw_chat, raw_global)
    except Exception:
        logger.warning("[composer] expression doc unreadable", exc_info=True)
        return ExpressionSettings(source="default",
                                  skip_reason="expression_absent")


async def speech_owner_block(chat_id: int | None) -> str:
    """Слои «Personality Core + Expression» для речевых маршрутов ВНЕ композера.

    UNIFIED-CORE (P0, владелец 20.10.2026): любой пользовательский текст бота —
    фактчек-вербализатор, Рассказчик саммари, search/checkup/youtube/web и
    fallback-пути — получает ТЕ ЖЕ слои личности и выражения, что и Direct
    (критерии спеки §5: один Core во всех маршрутах; нет исключений по имени
    модуля). Логическая схема «данные → жанровый контракт → Core + Expression
    → ответ»: блок дописывается ПОСЛЕ жанрового канона, 0 LLM-вызовов, второго
    Core/постпроцессора нет.

    Резолв — те же ``resolve_core_ref``/``resolve_expression_settings``
    (GLOBAL/per-chat + hot-apply), что у боевой сборки Direct. Порядок частей:
    Core, затем ``<Expression_Settings>`` (как в композере). Конфиг-слой
    недоступен или оба слоя пусты → ``""``: прежняя сборка остаётся байт-в-байт
    (OFF-паритет шва 2 — отсутствие инъекции не подменяет канон). Внутренние
    процессы (Stage-1 JSON, реранкер, tool-loop) блок НЕ получают — его
    передаёт только пользовательский маршрут. Никогда не бросает.
    """
    if not chat_id:
        return ""
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return ""
    parts: list[str] = []
    # SPEECH-SIMPLIFY §4: функциональные writer'ы получают тот же короткий
    # бытовой блок, но сохраняют собственный жанр; Core/Expression ниже.
    try:
        from services import prompt_style_blocks as _psb
        parts.append(_psb.speech_base_block())
    except Exception:          # pragma: no cover — fail-open
        logger.warning("[composer] speech base block unavailable",
                       exc_info=True)
    try:
        core = await resolve_core_ref(cid)
        if core is not None and core.enabled \
                and str(core.text or "").strip():
            parts.append(simplify_core_for_prompt(str(core.text)))
    except Exception:          # pragma: no cover — resolve уже fail-open
        logger.warning("[composer] speech_owner_block core failed",
                       exc_info=True)
    try:
        expr = await resolve_expression_settings(cid)
        if expr is not None and expr.enabled \
                and str(expr.text or "").strip():
            parts.append(str(expr.text))
    except Exception:          # pragma: no cover — resolve уже fail-open
        logger.warning("[composer] speech_owner_block expression failed",
                       exc_info=True)
    return "\n\n".join(parts)


async def speech_style_hint(chat_id: int | None) -> str:
    """Активный Style Policy hint для речевых маршрутов ВНЕ композера.

    SOUL-16/ASAP3 §1: hint строит единственный владелец — ``style_policy``
    (``resolve_style_policy_ref``); второго сборщика здесь нет. Нужен
    функциональным Writer'ам (фактчек и родственные публичные маршруты),
    которые собирают system-промпт сами, а не через ``compose_turn``:
    без этого активный слой стиля владельца до публичного Writer не доходил
    (баг §5.2 EVOL: «корректные активные инструкции не доходят»).

    Ось выключена/правил нет/слой недоступен → ``""``: сборка вызывающего
    остаётся байт-в-байт прежней. Никогда не бросает.
    """
    if not chat_id:
        return ""
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return ""
    try:
        ref = await resolve_style_policy_ref(cid)
    except Exception:          # pragma: no cover — resolve уже fail-open
        return ""
    if ref is None or not ref.enabled:
        return ""
    return str(ref.hint or "").strip()


def core_detail_label(core_ref: CoreRef | None) -> str:
    """Короткая метка выбора Core для трассы/Inspector (без текста промпта)."""
    if core_ref is None:
        return ""
    return (f"level={core_ref.detail_level} "
            f"reason={core_ref.detail_reason or 'n/a'} "
            f"origin={core_ref.origin or 'n/a'} "
            f"words={int(core_ref.compact_words or 0)} "
            f"doc={core_ref.document_revision or 'factory'}")


async def core_inspection(chat_id: int) -> dict:
    """Inspector-вид Core на текущем конфиге: редакция, версии, причина выбора.

    Inspector-side данные (SOUL-AMD.6.4/§10 «Effective Prompt Inspector»):
    что именно получит модель в слое ``core`` и почему. Сырого текста не
    отдаёт — ревизии/размеры/провенанс; тексты доступны владельцу отдельно.
    """
    try:
        ref = await resolve_core_ref(chat_id)
    except Exception:          # pragma: no cover — resolve уже fail-open
        ref = CoreRef(skip_reason="core_read_error")
    try:
        from services import prompt_registry as _pr
        factory_view = _pr.core_selection_view(None, source="default")
    except Exception:          # pragma: no cover — реестр недоступен
        factory_view = {}
    return {
        "chat_id": int(chat_id or 0),
        "doc_key": CORE_KEY,
        "level": ref.detail_level,
        "reason": ref.detail_reason,
        "source": ref.source,
        "origin": ref.origin,
        "document_revision": ref.document_revision,
        "active_revision": ref.revision,
        "chars": len(ref.text or ""),
        "compact_words": int(ref.compact_words or 0),
        "enabled": bool(ref.enabled),
        "skip_reason": ref.skip_reason,
        "factory_revisions": dict(factory_view.get("factory_revisions") or {}),
        "factory": {"full": factory_view.get("full") or {},
                    "compact": factory_view.get("compact") or {}},
        "edit_blocks": dict(factory_view.get("edit_blocks") or {}),
        "source_provenance": dict(factory_view.get("source_provenance") or {}),
    }


async def resolve_style_policy_ref(chat_id: int) -> StylePolicyRef:
    """Снимок effective Style Policy (единый владелец — ``services.style_policy``).

    ASAP3 §1: второго сборщика hint нет. Прежний fallback строил свой hint с
    дублирующими 400/5 и обрезкой посередине строки — он удалён. Если
    W3-модуль недоступен, снимок честно помечается ``style_policy_unavailable``
    (манифест не выдаёт частичный hint за полный). Никогда не бросает."""
    try:
        from services import style_policy as _sp
        ref = await _sp.resolve_style_policy_ref(chat_id)
        if ref is not None:
            return ref
    except Exception:          # pragma: no cover — защитная ветка
        logger.warning("[composer] style policy (W3) недоступна",
                       exc_info=True)
    return StylePolicyRef(skip_reason="style_policy_unavailable")


# ═════════════════════════════════════════════════════════════════════════════
# Per-turn snapshot (SOUL-15.5): один рендер личности на ход
# ═════════════════════════════════════════════════════════════════════════════

TURN_CACHE_MAX = 64
MANIFEST_CACHE_MAX = 32
_EVENT_DEDUP_MAX = 512
# Минимальная длина нормализованного фрагмента, который считается дублем
# owner-характера (короче — совпадение случайно: «бот», «да» и т.п.).
_DUPLICATE_MIN_CHARS = 8


@dataclass(frozen=True)
class TurnRefs:
    """Закреплённые на ход refs (immutable snapshot начатого запроса)."""

    core: CoreRef | None = None
    identity: IdentityRef | None = None
    style_policy: StylePolicyRef | None = None


_turn_lock = threading.Lock()
_turn_refs: "OrderedDict[tuple[int, str], TurnRefs]" = OrderedDict()
_manifest_lock = threading.Lock()
_manifests: "OrderedDict[tuple[int, str, str], PromptManifest]" = OrderedDict()
_last_layers: "OrderedDict[tuple[int, str], tuple[str, dict, int]]" = \
    OrderedDict()
_diffs: "OrderedDict[str, dict]" = OrderedDict()
_event_lock = threading.Lock()
_emitted_reasons: "OrderedDict[tuple[int, str], None]" = OrderedDict()

#: INS-TRACE/INS-EXACT: bounded журнал РЕАЛЬНЫХ provider-вызовов.
#: Хранит структуру + хэши + санитизированный точный текст (owner-debug).
#: Не телеметрия и не публичный лог: доступ только через Inspector.
PROVIDER_CALL_MAX = 24
_PROVIDER_TEXT_MAX = 60000
_provider_lock = threading.Lock()
_provider_calls: "OrderedDict[str, dict]" = OrderedDict()
#: Уникальный ключ записи: одинаковые тела ретраев не перезаписывают друг
#: друга (иначе «все попытки» фактически схлопывались в одну).
_provider_seq = itertools.count(1)


def _turn_key(chat_id: int, run_id: str | None) -> tuple[int, str] | None:
    if not run_id:
        return None
    return (int(chat_id or 0), str(run_id))


def pin_turn_refs(chat_id: int, run_id: str | None = None, *,
                  core: CoreRef | None = None,
                  identity: IdentityRef | None = None,
                  style_policy: StylePolicyRef | None = None) -> TurnRefs:
    """Закрепить refs за ходом: первый вызов выигрывает, далее — кэш.

    Так две LLM-стадии одного хода (tool-phase и L2 Writer) получают ОДИН
    рендер ``identity`` c одной ревизией, а правка Core/Policy в середине
    хода не раскалывает сборку на «половину новых правил» (SOUL-15.5).
    Без ``run_id`` — обычный проходной вызов (ничего не закрепляется).
    """
    key = _turn_key(chat_id, run_id)
    if key is None:
        return TurnRefs(core=core, identity=identity, style_policy=style_policy)
    with _turn_lock:
        stored = _turn_refs.get(key)
        if stored is None:
            stored = TurnRefs(core=core, identity=identity,
                              style_policy=style_policy)
        else:
            # Сливаем по слоям: уже закреплённый ref выигрывает, `None` в
            # закреплённом наборе означает «эта стадия слой не поставляет»
            # (turn_snapshot не знает про identity, tool-phase — про policy).
            stored = TurnRefs(
                core=stored.core if stored.core is not None else core,
                identity=(stored.identity if stored.identity is not None
                          else identity),
                style_policy=(stored.style_policy
                              if stored.style_policy is not None
                              else style_policy))
        _turn_refs[key] = stored
        while len(_turn_refs) > TURN_CACHE_MAX:
            _turn_refs.popitem(last=False)
        return stored


def recall_turn_refs(chat_id: int, run_id: str | None) -> TurnRefs | None:
    """Что уже закреплено за ходом (для тестов/Inspector/diagnostics)."""
    key = _turn_key(chat_id, run_id)
    if key is None:
        return None
    with _turn_lock:
        return _turn_refs.get(key)


def identity_from_text(text: str, *, chat_id: int = 0,
                       run_id: str | None = None, source: str = "chat",
                       skipped: str = "") -> IdentityRef:
    """Единый рендер личности: строится из УЖЕ собранного блока.

    Может быть вызван в обеих стадиях хода — ревизия останется общей.
    """
    ref = IdentityRef(text=str(text or ""), revision=_sha16(text),
                      source=str(source or "chat"), skipped=skipped)
    pinned = pin_turn_refs(chat_id, run_id, identity=ref).identity
    return pinned if pinned is not None else ref


async def turn_snapshot(chat_id: int, run_id: str | None) -> TurnRefs:
    """Core/Policy хода: резолв + пин (SOUL-15.5). Никогда не бросает.

    Значения читаются ОДИН раз за ход: правка Core/Style Policy в середине
    хода не даёт «половину новых правил» ни в tool-phase, ни в L2 Writer.
    """
    try:
        core = await resolve_core_ref(chat_id)
    except Exception:          # pragma: no cover — resolve уже fail-open
        core = CoreRef(skip_reason="core_read_error")
    try:
        policy = await resolve_style_policy_ref(chat_id)
    except Exception:          # pragma: no cover
        policy = StylePolicyRef(skip_reason="style_policy_read_error")
    return pin_turn_refs(chat_id, run_id, core=core, style_policy=policy)


async def resolve_base_source(chat_id: int, pg_key: str,
                              code_default: str = "") -> str:
    """Провенанс базы канала: chat override → global → default (код-канон)."""
    try:
        from services import hot_config as hot
        from services.chat_params import get_chat_param as _cpg
    except Exception:          # pragma: no cover
        return "default"
    try:
        value = await _cpg(chat_id, pg_key, None)
    except Exception:
        return "default"
    if value is None:
        return "default"
    try:
        global_value = hot.get(pg_key, None)
    except Exception:
        global_value = None
    if global_value is None:
        return "chat"
    return "global" if str(global_value) == str(value) else "chat"


def plan_ref_from_response_plan(response_plan: Any, extent_block: str,
                                *, source: str = "l1") -> PlanRef | None:
    """PlanRef из ResponsePlan: extent едет ЗНАЧЕНИЕМ (без алиасов, шов 3)."""
    if response_plan is None:
        return None
    extent = str(getattr(response_plan, "extent", "") or "")
    structure = str(getattr(response_plan, "structure", "") or "")
    tone = str(getattr(response_plan, "tone", "") or "")
    strategy = str(getattr(response_plan, "comic_strategy", "") or "")
    text = str(extent_block or "")
    return PlanRef(
        text=text, revision=(sha12(text) if text else ""), source=str(source),
        extent=extent, structure=structure, tone=tone,
        comic_strategy=strategy)


def reset_state() -> None:
    """Сброс кэшей композера (тесты, Inspector, длинный рантайм)."""
    with _turn_lock:
        _turn_refs.clear()
    with _manifest_lock:
        _manifests.clear()
        _last_layers.clear()
    with _event_lock:
        _emitted_reasons.clear()
    reset_provider_calls()


def get_manifest(chat_id: int, *, run_id: str | None = None,
                 writer: str | None = None) -> PromptManifest | None:
    """Манифест хода (seam W6 Prompt Inspector: «покажи effective layers»)."""
    with _manifest_lock:
        if writer is not None:
            return _manifests.get((int(chat_id or 0), str(run_id or "-"),
                                   str(writer)))
        for key, manifest in reversed(list(_manifests.items())):
            if key[0] != int(chat_id or 0):
                continue
            if run_id and key[1] != str(run_id):
                continue
            return manifest
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Сборка
# ═════════════════════════════════════════════════════════════════════════════


def _trace(layer: str, *, block_id: str = "", text: str = "", owner: str = "",
           source: str = "code", revision: str = "", rendered: bool = False,
           skip_reason: str = "", conflict: str = "",
           detail: str = "") -> LayerTrace:
    origin = str(source or "code")
    if origin not in SOURCES:
        # Ref может называть свой этап («l1»/«library»); контракт трассы —
        # закрытый набор провенанса, поэтому неизвестный ярлык → `code`.
        origin = "code"
    return LayerTrace(
        layer=layer,
        block_id=str(block_id or layer),
        owner=str(owner or ""),
        source=origin,
        revision=str(revision or ""),
        chars=len(text or ""),
        tokens=(estimate_tokens(text) if rendered and text else 0),
        rendered=bool(rendered),
        skip_reason=str(skip_reason or ""),
        conflict=str(conflict or ""),
        detail=str(detail or ""),
        # Текст блока хранится только для ВКЛЮЧЁННЫХ слоёв: пропущенный слой
        # объясняется причиной, а не содержимым, которого модель не видела.
        text=(str(text) if rendered and text else ""),
    )


def _block_reason(block: Block, default: str) -> str:
    if not block.enabled:
        return block.skip_reason or default
    if not str(block.text or "").strip():
        return block.skip_reason or default
    return ""


def _append(parts: list[str], text: str) -> bool:
    if str(text or "").strip():
        parts.append(str(text))
        return True
    return False


def _joined(parts: Sequence[str]) -> str:
    return "\n\n".join(p for p in parts if p)


#: SPEECH-SIMPLIFY §4 / SPEECH-P0-CORE-SERIOUS: ИСТОРИЧЕСКИЕ слепки точных
#: абзацев, которые раньше вырезались из payload. P0-CORRECTIVE (25.10.2026,
#: §3) снял обрезку: активный owner-Core уходит в модель целиком, поэтому
#: литералы ниже в сборке не участвуют и сохранены только как история.
_CORE_HUMOR_TECHNIQUE_PARAGRAPH = (
    "Как рождается юмор. Когда разговор располагает к шутке, ищи неожиданную "
    "интерпретацию сказанного. Можешь принять оговорку, нелепую предпосылку "
    "или метафору буквально и исследовать её последствия. Если нашёл смешную "
    "идею, развивай её конкретными бытовыми деталями, воображаемыми правилами, "
    "предметами и ситуациями. Абсурд может нарастать, пока не закончится "
    "неожиданным, но внутренне связным выводом. Смешивай несовместимые "
    "области - бытовуху, философию, бюрократию, экономику, биологию, "
    "технологии, религию и устройство общества. Интересны не случайные "
    "сравнения, а связи, которые после прочтения кажутся почти логичными."
)
_CORE_RHYTHM_PARAGRAPH = (
    "Ритм. Не придерживайся одной длины или композиции ответа. Иногда "
    "достаточно трёх слов, иногда шутке требуется несколько предложений и "
    "нарастающий абсурд. Не обрывай удачную мысль ради искусственной "
    "краткости. Можно начать с неожиданного вывода, детали, возражения, "
    "воображаемой сцены или продолжения чужой мысли. Не объясняй собственные "
    "шутки, не объявляй используемые приёмы."
)


#: SPEECH-P0-CORE-SERIOUS (25.10.2026, active-core.md §5): точный
#: абзац P2 активного owner-Core (759 симв., sha12 e551049be4d0) —
#: байт-в-байт равен PREV_PERSONALITY_CORE v1/v2. Конкурирует с
#: короткой HUMOR-директивой: эскалация, «развивай идею»,
#: несколько предложений ради шутки.
_CORE_ACTIVE_HUMOR_PARAGRAPH = (
    "**Как рождается юмор.** Когда разговор располагает к шутке, ищи "
    "неожиданную интерпретацию сказанного. Можешь принять случайную "
    "оговорку, нелепую предпосылку или метафору буквально и "
    "исследовать, к каким последствиям это приведёт. Если нашёл смешную "
    "идею, развивай её, а не бросай после первой фразы. Добавляй "
    "неожиданные, но логически связанные последствия, конкретные "
    "бытовые детали, воображаемые правила, предметы и ситуации. Абсурд "
    "может постепенно нарастать, пока не закончится неожиданным "
    "выводом. Свободно смешивай несовместимые области: бытовуху, "
    "философию, бюрократию, экономику, биологию, технологии, религию, "
    "криминалистику, устройство общества. Интересны не случайные "
    "сравнения, а неожиданные связи, которые после прочтения кажутся "
    "почти логичными."
)

#: Точный абзац P5 активного owner-Core (498 симв.,
#: sha12 3cad0802336d) — оперативный регулятор длины/композиции;
#: конкурирует с коротким RESPONSE_LENGTH.
_CORE_ACTIVE_RHYTHM_PARAGRAPH = (
    "**Ритм.** Не придерживайся одной длины ответа. Иногда достаточно "
    "трёх слов или одного слова. Иногда хорошая шутка требует "
    "нескольких предложений и нарастающего абсурда. Не обрывай удачную "
    "мысль ради искусственной краткости. Не используй постоянно одну "
    "композицию. Можешь начать с неожиданного вывода, нелепой детали, "
    "возражения, воображаемой сцены или продолжения мысли другого "
    "человека. Не объясняй собственные шутки, не называй использованные "
    "приёмы и не сообщай, что сейчас будешь иронизировать."
)


def simplify_core_for_prompt(text: str) -> str:
    """Payload-сборка Core: БЕЗ обрезки, только fail-safe нормализация входа.

    P0-CORRECTIVE (25.10.2026, §3 source-owner-p0-corrective «проверить
    применение полного актуального Core без произвольного бюджетного
    обрезания»): прежний allowlist вырезал из активного owner-Core абзацы
    P2/P5/P3 (759+498+785 симв.) и отдавал модели 1246 вместо 3294. Это
    произвольная подмена авторского текста на сборке, поэтому фильтр снят:
    функция оставлена как identity/fail-safe (совместимость вызовов и
    ``speech_owner_block``), хранимый Core в БД не меняется, ни один абзац
    не удаляется и не переписывается.

    Точные прежние абзацы-литералы ниже сохранены как исторические слепки
    (``_CORE_*``): они больше не участвуют в сборке.
    """
    try:
        return str(text or "")
    except Exception:      # pragma: no cover — сборка промпта не падает
        return ""


def _compose(plan: PromptPlan) -> PromptManifest:
    from services import prompt_style_blocks as psb
    from services import mca_expression as _expr_mod

    gates = plan.gates if isinstance(plan.gates, GateState) \
        else gates_from_config()
    profile = plan.profile if plan.profile in PROFILES else PROFILE_MACHINE_JSON
    writer = str(plan.writer or "")
    chat_id = int(plan.chat_id or 0)
    speech = profile in _SPEECH_PROFILES
    core_allowed = profile in _CORE_PROFILES
    profile_reason = _PROFILE_REASON.get(profile, "profile:machine_stage")

    traces: list[LayerTrace] = []
    conflicts: list[ConflictRecord] = []
    parts: list[str] = []
    # QUOTA-REMOVAL (ADDENDUM #3 §2.7): аддитивного бюджета инструкций нет.
    # Слои рендерятся по порядку и по смыслу (owner/gates/profile), а не по
    # остатку квоты. Реальное окно модели — `model_capacity` на стороне вызова.

    # ── 1. channel_contract: техническая база канала/профиля ────────────────
    base_raw = str(plan.base_prompt or "")
    mode_candidate = ""
    channel_output = ""
    base_reason = ""
    if speech and plan.include_mode_block:
        mode_candidate, base_text, mode_block = psb.resolve_mode_parts(
            base_raw, plan.response_mode,
            extent_block=(plan.response_plan.text
                          if plan.response_plan is not None else ""),
            modes_enabled=bool(gates.smart_verbalizer_modes_enabled))
        if not gates.smart_verbalizer_modes_enabled:
            # Тихая подстановка PREV-канона больше не «тихая»: причина видна.
            base_reason = "verbilizer_modes_disabled"
        if mode_candidate == "deep_research":
            channel_output = psb.format_block(plan.channel,
                                             html_safe=plan.html_safe)
    else:
        # tool-phase: база канала как есть (режимный блок на этом пути
        # никогда не рендерился), полнота едет слоем response_plan.
        base_text = base_raw
    base_rendered = _append(parts, base_text)
    if not base_rendered:
        base_reason = "channel_contract_missing"
    traces.append(_trace(
        LAYER_CHANNEL_CONTRACT, block_id="channel_canon", text=base_text,
        owner="channel", source=str(plan.base_source or "default"),
        revision=sha12(base_text), rendered=base_rendered,
        skip_reason=base_reason))
    # MODE-совместимость: часть L1-базы канала (source-of-truth §1.2), а не
    # план. Extent/план ЗАМЕНЯЕТ её (как и в `compose_verbalizer_system`),
    # поэтому при непустом плане блока нет вообще.
    mode_compat = ""
    if speech and plan.include_mode_block:
        plan_text_now = (str(plan.response_plan.text or "")
                         if plan.response_plan is not None else "")
        if not plan_text_now.strip():
            mode_compat = str(mode_block or "")
    if mode_compat:
        _append(parts, mode_compat)
        traces.append(_trace(
            LAYER_CHANNEL_CONTRACT, block_id="mode_block", text=mode_compat,
            owner="legacy_canon", source="code",
            revision=sha12(mode_compat), rendered=True))

    # ── 2. core: Personality Core (единственная точка инъекции) ─────────────
    core_text = ""
    core_ref = plan.core
    core_detail = core_detail_label(core_ref)
    if not core_allowed:
        traces.append(_trace(
            LAYER_CORE, block_id="core", owner="core",
            revision=(core_ref.revision if core_ref is not None else ""),
            skip_reason=profile_reason, detail=core_detail))
    elif not gates.character_core_enabled:
        traces.append(_trace(
            LAYER_CORE, block_id="core", owner="core",
            revision=(core_ref.revision if core_ref is not None else ""),
            source=(core_ref.source if core_ref is not None else "default"),
            skip_reason="core_disabled", detail=core_detail))
    else:
        reason = ""
        if core_ref is None:
            reason = "core_absent"
        elif not core_ref.enabled:
            reason = core_ref.skip_reason or "core_disabled"
        elif not str(core_ref.text or "").strip():
            reason = core_ref.skip_reason or "core_absent"
        if reason:
            traces.append(_trace(
                LAYER_CORE, block_id="core", owner="core",
                revision=(core_ref.revision if core_ref is not None else ""),
                source=(core_ref.source if core_ref is not None else "default"),
                skip_reason=reason, detail=core_detail))
        else:
            core_text = simplify_core_for_prompt(str(core_ref.text))
            # QUOTA-REMOVAL (ADDENDUM #3 §2.7): Core — обязательный слой и
            # никакой квотой не вытесняется и не понижается. `detail_level`
            # владельца — единственный источник выбора редакции (см.
            # `prompt_registry.core_selection`).
            _append(parts, core_text)
            traces.append(_trace(
                LAYER_CORE, block_id="core", text=core_text, owner="core",
                source=core_ref.source, revision=core_ref.revision,
                rendered=True, detail=core_detail))

    # ── 3. identity: имя/биография/отношения/owner style ────────────────────
    identity_text = ""
    identity_ref = plan.identity
    if not speech:
        traces.append(_trace(
            LAYER_IDENTITY, block_id="identity", owner="persona",
            revision=(identity_ref.revision if identity_ref is not None else ""),
            skip_reason=profile_reason))
    elif not gates.persona_enabled:
        traces.append(_trace(
            LAYER_IDENTITY, block_id="identity", owner="persona",
            revision=(identity_ref.revision if identity_ref is not None else ""),
            skip_reason="persona_disabled"))
    else:
        raw_identity = str(identity_ref.text or "") \
            if identity_ref is not None else ""
        degraded = "" if gates.character_layers_enabled \
            else "character_layers_disabled"
        source = str(identity_ref.source) if identity_ref is not None else "chat"
        if not raw_identity.strip():
            reason = (identity_ref.skipped if identity_ref is not None else "") \
                or _ABSENT_REASON[LAYER_IDENTITY]
            traces.append(_trace(
                LAYER_IDENTITY, block_id="identity", owner="persona",
                source=source, skip_reason=reason))
        else:
            identity_text = raw_identity
            revision = (identity_ref.revision if identity_ref is not None
                        else "") or _sha16(identity_text)
            duplicate = _duplicate_character_segment(identity_text, core_text)
            conflict_id = ""
            if duplicate:
                kept = [line for line in identity_text.splitlines()
                        if line.strip() != duplicate.strip()]
                identity_text = "\n".join(kept).strip("\n ")
                conflict_id = "duplicate_owner_character"
                conflicts.append(ConflictRecord(
                    conflict_id=conflict_id, outcome="keep_stronger",
                    layer=LAYER_IDENTITY, block_id="identity",
                    detail="owner_character_already_rendered_by_core",
                    provenance=f"core:{sha12(core_text)}|identity:{revision}"))
                revision = _sha16(identity_text)
            _append(parts, identity_text)
            traces.append(_trace(
                LAYER_IDENTITY, block_id="identity", text=identity_text,
                owner="persona", source=source,
                revision=revision, rendered=True, skip_reason=degraded,
                conflict=conflict_id))

    # ── 4. self_model_traits ────────────────────────────────────────────────
    self_model = plan.self_model
    if not speech:
        traces.append(_trace(
            LAYER_SELF_MODEL_TRAITS, block_id="self_model_traits",
            owner="self_model", skip_reason=profile_reason))
    elif self_model is None or not str(self_model.text or "").strip():
        # В текущем рантайме черты/кадр SelfModel рендерятся ВНУТРИ
        # личности (bot_persona.resolve_character_context →
        # build_persona_prompt_block), поэтому отдельного блока нет. Это не
        # молчаливая потеря: причина названа явно.
        traces.append(_trace(
            LAYER_SELF_MODEL_TRAITS, block_id="self_model_traits",
            owner="self_model", skip_reason="self_model_folded_into_identity"))
    else:
        _append(parts, self_model.text)
        traces.append(_trace(
            LAYER_SELF_MODEL_TRAITS, block_id="self_model_traits",
            text=self_model.text, owner="self_model",
            source=str(self_model.source or "chat"),
            revision=str(self_model.revision or _sha16(self_model.text)),
            rendered=True))

    # ── 5. context_lessons: scoped prefs + verified lessons + сигнал речи ───
    lessons_traces: list[LayerTrace] = []
    if not speech:
        lessons_traces.append(_trace(
            LAYER_CONTEXT_LESSONS, block_id="context_lessons",
            owner="legacy_canon", skip_reason=profile_reason))
    else:
        ordered: list[tuple[Block, str]] = []
        ordered.extend((b, "l1") for b in (plan.scoped_requests or ()))
        ordered.extend((b, "experience") for b in (plan.lessons or ()))
        if plan.speech is not None:
            ordered.append((plan.speech, "l1"))
        for block, owner in ordered:
            reason = _block_reason(block, _ABSENT_REASON[LAYER_CONTEXT_LESSONS])
            rendered = not reason
            if rendered:
                _append(parts, block.text)
            lessons_traces.append(_trace(
                LAYER_CONTEXT_LESSONS,
                block_id=str(block.block_id or LAYER_CONTEXT_LESSONS),
                text=str(block.text if rendered else ""), owner=owner,
                source=str(block.source or "code"),
                revision=str(block.revision or
                             (_sha12_safe(block.text) if rendered else "")),
                rendered=rendered, skip_reason=reason))
        if not lessons_traces:
            lessons_traces.append(_trace(
                LAYER_CONTEXT_LESSONS, block_id=LAYER_CONTEXT_LESSONS,
                owner="experience", skip_reason="lessons_absent"))
    traces.extend(lessons_traces)

    # ── 6. response_plan: extent/структура/тон + (опц.) comic_strategy ──────
    plan_ref = plan.response_plan
    plan_text = str(plan_ref.text or "") if plan_ref is not None else ""
    if not speech:
        traces.append(_trace(
            LAYER_RESPONSE_PLAN, block_id="response_plan", owner="l1",
            skip_reason=profile_reason))
    elif not gates.response_plan_enabled:
        traces.append(_trace(
            LAYER_RESPONSE_PLAN, block_id="response_plan", owner="l1",
            skip_reason="response_plan_disabled"))
    elif not plan_text.strip():
        reason = ""
        if plan_ref is not None:
            reason = plan_ref.skip_reason
        traces.append(_trace(
            LAYER_RESPONSE_PLAN, block_id="response_plan", owner="l1",
            source=(str(plan_ref.source) if plan_ref is not None else "l1"),
            revision=(str(plan_ref.revision) if plan_ref is not None else ""),
            skip_reason=reason or "response_plan_absent"))
    else:
        _append(parts, plan_text)
        plan_revision = str(plan_ref.revision or _sha16(plan_text))
        plan_conflict = ""
        if str(plan_ref.extent or "").strip() and _extent_unknown(
                plan_ref.extent):
            plan_conflict = "one_word_not_supported"
            conflicts.append(ConflictRecord(
                conflict_id=plan_conflict, outcome="conflict_reported",
                layer=LAYER_RESPONSE_PLAN, block_id="response_plan",
                detail=f"extent={plan_ref.extent}",
                provenance=f"plan:{plan_revision}"))
        traces.append(_trace(
            LAYER_RESPONSE_PLAN, block_id="response_plan", text=plan_text,
            owner="l1", source=str(plan_ref.source or "l1"),
            revision=plan_revision, rendered=True, conflict=plan_conflict))

    # ── 7. speech_base: короткая манера/юмор/длина/достоверность ───────────
    # P0 SPEECH-SIMPLIFY §2.1-2.3/§5: один короткий блок существующего
    # речевого слоя; не зависит от режима мата и не дублирует Core.
    _base_l = str(plan.base_prompt or "").lower()
    _functional_writer = (
        any(tag in str(plan.writer or "").lower()
            for tag in ("factcheck", "summary", "checkup", "search", "youtube",
                        "web"))
        or any(marker in _base_l
               for marker in ("фактчекер", "betterstack", "сводк", "checkup",
                              "summary")))
    speech_base_text = (psb.speech_base_block()
                        if profile in ("speech_plain", "speech_rich")
                        and not _functional_writer else "")
    if speech_base_text and speech_base_text not in "\n".join(parts):
        _append(parts, speech_base_text)

    # ── 7. expression: эмоциональная температура/резкость (soft) ───────────
    expression = plan.expression
    expression_final = ""
    if not speech:
        traces.append(_trace(LAYER_EXPRESSION, block_id="expression",
                             owner="core", skip_reason=profile_reason))
    elif expression is None or not str(expression.text or "").strip() \
            or not expression.enabled:
        reason = (expression.skip_reason if expression is not None else "") \
            or "expression_absent"
        traces.append(_trace(
            LAYER_EXPRESSION, block_id="expression", owner="core",
            source=(str(expression.source) if expression is not None
                    else "global"),
            revision=(str(expression.revision) if expression is not None
                      else ""),
            skip_reason=reason))
    else:
        text = str(expression.text)
        # P0-E v2 (24.10.2026): тот же режим речи повторяется ФИНАЛЬНЫМ
        # контрактом в самом конце system. Замер: слой стоит на 85.0–96.3%
        # полной сборки, а последние ~320 симв. занимает другой слой —
        # поэтому хвост получает ту же директиву с явной пометкой приоритета.
        # Источник текста один (`mca_expression.PROFANITY_INSTRUCTIONS`):
        # второго регулятора частоты, квот и постпроцессора нет.
        expression_final = _expr_mod.render_expression_final_contract(
            getattr(expression, "mode", ""))
        # QUOTA-REMOVAL (ADDENDUM #3 §2.7): `budget_excluded` для Expression
        # удалён вместе с аддитивным бюджетом — режим речи не может исчезнуть
        # из payload из-за локальной квоты.
        _append(parts, text)
        traces.append(_trace(
            LAYER_EXPRESSION, block_id="expression",
            text=(text + ("\n\n" + expression_final if expression_final
                          else "")),
            owner="core", source=str(expression.source or "global"),
            revision=str(expression.revision or _sha16(text)),
            rendered=True,
            detail=(f"final_contract=tail chars={len(expression_final)}"
                    if expression_final else "")))

    # ── 8. humor_craft (приёмы, не личность; 0 доп. LLM) ───────────────────
    if not speech:
        traces.append(_trace(LAYER_HUMOR_CRAFT, block_id="humor_craft",
                             owner="library", skip_reason=profile_reason))
    elif not gates.humor_craft_enabled:
        # SOUL-06.7: диагностическое выключение ремесла (Core живёт).
        traces.append(_trace(LAYER_HUMOR_CRAFT, block_id="humor_craft",
                             owner="library",
                             revision=(plan.humor.revision
                                       if plan.humor is not None else ""),
                             skip_reason="humor_disabled"))
    elif plan.humor is None or not str(plan.humor.text or "").strip():
        reason = (plan.humor.skip_reason if plan.humor is not None else "") \
            or ("humor_no_strategy")
        strategy = str(getattr(plan.response_plan, "comic_strategy", "") or "") \
            if plan.response_plan is not None else ""
        if plan.humor is None and strategy and strategy != "none":
            reason = "humor_disabled"
        traces.append(_trace(LAYER_HUMOR_CRAFT, block_id="humor_craft",
                             owner="library",
                             revision=(plan.humor.revision
                                       if plan.humor is not None else ""),
                             skip_reason=reason))
    else:
        reason = "" if plan.humor.enabled else (
            plan.humor.skip_reason or "humor_disabled")
        if reason:
            traces.append(_trace(LAYER_HUMOR_CRAFT, block_id="humor_craft",
                                 owner="library",
                                 revision=plan.humor.revision,
                                 skip_reason=reason))
        else:
            humor_text = str(plan.humor.text)
            if humor_text.strip() and any(
                    humor_text.strip() in str(p) for p in parts):
                traces.append(_trace(
                    LAYER_HUMOR_CRAFT, block_id="humor_craft",
                    owner="library", revision=plan.humor.revision,
                    skip_reason="humor_folded_into_speech_base"))
            else:
                _append(parts, plan.humor.text)
                traces.append(_trace(
                    LAYER_HUMOR_CRAFT, block_id="humor_craft",
                    text=plan.humor.text, owner="library",
                    source=str(plan.humor.source or "library"),
                    revision=str(plan.humor.revision or _sha16(
                        plan.humor.text)),
                    rendered=True))

    # ── 9. few_shot ─────────────────────────────────────────────────────────
    # ADD-EXP §3.2/§3.3: набор регистра речи идёт ДО humor-примеров, своим
    # блоком (owner `core`) и со своими честными причинами пропуска.
    expr_examples = tuple(getattr(plan, "expression_examples", ()) or ())
    if not speech:
        traces.append(_trace(LAYER_FEW_SHOT, block_id="expression_examples",
                             owner="core", skip_reason=profile_reason))
    elif not gates.expression_examples_enabled:
        traces.append(_trace(LAYER_FEW_SHOT, block_id="expression_examples",
                             owner="core",
                             skip_reason="expression_examples_disabled"))
    elif not expr_examples:
        traces.append(_trace(LAYER_FEW_SHOT, block_id="expression_examples",
                             owner="core",
                             skip_reason="expression_examples_absent"))
    else:
        for block in expr_examples:
            reason = _block_reason(block, "expression_examples_absent")
            if not reason and not gates.expression_examples_enabled:
                reason = "expression_examples_disabled"
            rendered = not reason
            if rendered:
                _append(parts, block.text)
            traces.append(_trace(
                LAYER_FEW_SHOT,
                block_id=block.block_id or "expression_examples",
                text=block.text if rendered else "", owner="core",
                source=str(block.source or "global"),
                revision=str(block.revision or
                             (_sha12_safe(block.text) if rendered else "")),
                rendered=rendered, skip_reason=reason))
    if not speech:
        traces.append(_trace(LAYER_FEW_SHOT, block_id="few_shot",
                             owner="library", skip_reason=profile_reason))
    elif not gates.humor_library_enabled and not plan.samples:
        traces.append(_trace(LAYER_FEW_SHOT, block_id="few_shot",
                             owner="library", skip_reason="samples_disabled"))
    elif not plan.samples:
        traces.append(_trace(LAYER_FEW_SHOT, block_id="few_shot",
                             owner="library", skip_reason="samples_absent"))
    else:
        for block in plan.samples:
            reason = _block_reason(block, "samples_absent")
            if not reason and not gates.humor_library_enabled:
                reason = "samples_disabled"
            rendered = not reason
            if rendered:
                _append(parts, block.text)
            traces.append(_trace(
                LAYER_FEW_SHOT, block_id=block.block_id or "few_shot",
                text=block.text if rendered else "", owner="library",
                source=str(block.source or "library"),
                revision=str(block.revision or
                             (_sha12_safe(block.text) if rendered else "")),
                rendered=rendered, skip_reason=reason))

    # ── 10. style_policy_hint (короткий hint; исполнение — W3) ─────────────
    policy = plan.style_policy
    if not speech:
        traces.append(_trace(LAYER_STYLE_POLICY_HINT,
                             block_id="style_policy_hint",
                             owner="style_policy", skip_reason=profile_reason))
    elif not gates.speech_style_policy_enabled:
        traces.append(_trace(
            LAYER_STYLE_POLICY_HINT, block_id="style_policy_hint",
            owner="style_policy",
            revision=(policy.revision if policy is not None else ""),
            skip_reason="style_policy_disabled"))
    elif policy is None or not str(policy.hint or "").strip() \
            or not policy.enabled:
        reason = (policy.skip_reason if policy is not None else "") \
            or "style_policy_absent"
        traces.append(_trace(
            LAYER_STYLE_POLICY_HINT, block_id="style_policy_hint",
            owner="style_policy",
            revision=(policy.revision if policy is not None else ""),
            source=(str(policy.source) if policy is not None else "default"),
            skip_reason=reason))
    else:
        hint_text = str(policy.hint)
        # QUOTA-REMOVAL (ADDENDUM #3 §2.7): прод-симптом
        # `style_policy_hint → budget_excluded` устранён вместе с квотой —
        # hint рендерится всегда, когда он активен и разрешён осью.
        _append(parts, hint_text)
        traces.append(_trace(
            LAYER_STYLE_POLICY_HINT, block_id="style_policy_hint",
            text=hint_text, owner="style_policy",
            source=str(policy.source or "default"),
            revision=str(policy.revision or _sha16(hint_text)),
            rendered=True))

    # ── 11. channel_output: финальные ограничения вывода канала ────────────
    if not speech:
        traces.append(_trace(LAYER_CHANNEL_OUTPUT, block_id="channel_output",
                             owner="channel", skip_reason=profile_reason))
    elif not str(channel_output or "").strip():
        traces.append(_trace(LAYER_CHANNEL_OUTPUT, block_id="channel_output",
                             owner="channel",
                             skip_reason="channel_output_not_required"))
    else:
        _append(parts, channel_output)
        traces.append(_trace(
            LAYER_CHANNEL_OUTPUT, block_id="channel_output",
            text=channel_output, owner="channel",
            source=str(plan.channel or "plain"),
            revision=sha12(channel_output), rendered=True))

    # ── 12. expression final contract: тот же режим речи в САМОМ КОНЦЕ ──────
    # Слой стоит НЕ в конце сборки (85–96%), последним модель читает другой
    # блок. Финальный контракт повторяет ту же директиву из единственного
    # источника (`mca_expression.PROFANITY_INSTRUCTIONS`) с пометкой
    # приоритета; второго регулятора частоты не появляется. Учтён в трассе
    # слоя `expression` (`detail=final_contract=tail`), отдельного слоя нет.
    if expression_final:
        _append(parts, expression_final)

    system = _joined(parts)
    # INS-CONFLICT: устаревшие служебные метки `SOUL-*` не должны попадать в
    # модель. Проверка по ФАКТИЧЕСКИ отрендеренным блокам (не по конфигу):
    # метка есть в payload → честный conflict_reported с провенансом.
    for trace in traces:
        if not trace.rendered or not trace.text:
            continue
        found = _SOUL_LABEL_RE.findall(trace.text)
        if not found:
            continue
        conflicts.append(ConflictRecord(
            conflict_id="soul_legacy_label_in_payload",
            outcome="conflict_reported", layer=trace.layer,
            block_id=trace.block_id,
            detail="labels=%s" % ",".join(sorted(set(found))[:4]),
            provenance="%s:%s" % (trace.owner or "code",
                                  trace.revision or sha12(trace.text))))
    versions = _versions(plan, profile, base_text, core_text, identity_text,
                         lessons_traces, traces)
    manifest = PromptManifest(
        system=system,
        user_parts=tuple(str(p) for p in (plan.user_parts or ())),
        layers=tuple(traces),
        versions=versions,
        flags=gates.as_flags(),
        conflicts=tuple(conflicts),
        manifest_id=_manifest_id(system, plan.user_parts or (), versions),
        profile=profile,
        writer=writer,
        chat_id=chat_id,
        run_id=(str(plan.run_id) if plan.run_id else None),
        tokens_total=estimate_tokens(system),
    )
    _remember(manifest)
    return manifest


def _sha12_safe(text: str) -> str:
    try:
        return sha12(text)
    except Exception:          # pragma: no cover
        return ""


def _extent_unknown(extent: str) -> bool:
    """Значение extent, которого нет в ``response_extent.EXTENTS`` (шов 3)."""
    try:
        from services import response_extent as _extent
        return str(extent).strip() not in _extent.EXTENTS
    except Exception:          # pragma: no cover
        return False


def _duplicate_character_segment(identity: str, core: str) -> str:
    """Найти owner-характер, который уже пришёл слоем Core (SOUL-03.6).

    Возвращает сегмент identity, который надо снять (или ""). Работает по
    значимым строкам: ``Характер: …`` и любые строки, дословно совпадающие с
    Core. Ничего не «сочиняет» и не трогает остальную персону.
    """
    core_norm = _norm_for_compare(core)
    if not core_norm:
        return ""
    for line in str(identity or "").splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        value = candidate.split(":", 1)[1].strip() if ":" in candidate \
            else candidate
        norm = _norm_for_compare(value)
        if len(norm) < _DUPLICATE_MIN_CHARS:
            continue
        if norm and norm in core_norm:
            return candidate
    return ""


def _versions(plan: PromptPlan, profile: str, base_text: str, core_text: str,
              identity_text: str, lessons_traces: Sequence[LayerTrace],
              traces: Sequence[LayerTrace]) -> dict[str, str]:
    """Версии всех источников (§2: core/style_policy/identity/...)."""
    policy = plan.style_policy
    samples = plan.samples
    plan_ref = plan.response_plan
    lessons_rev = ",".join(t.revision for t in lessons_traces if t.revision)
    sample_rev = ",".join(
        str(s.revision or s.library_version or sha12(s.text))
        for s in samples) if samples else ""
    expr_trace = next((t for t in traces
                       if t.layer == LAYER_EXPRESSION and t.rendered), None)
    expr_examples_trace = next(
        (t for t in traces if t.block_id == "expression_examples"
         and t.rendered), None)
    identity = plan.identity
    core = plan.core
    return {
        "core": (core.revision if core is not None else ""),
        # Какая редакция Core действует и почему (SOUL-AMD.1.1/§10):
        # «compact:owner_setting» | «full:owner_setting» | «compact:factory_default».
        # QUOTA-REMOVAL (ADDENDUM #3 §2.7): причины `context_budget` больше нет.
        "core_detail": ((f"{core.detail_level}:{core.detail_reason}"
                         if core is not None and core.detail_reason else "")
                        if core is not None else ""),
        "style_policy": (policy.revision if policy is not None else ""),
        "identity": ((identity.revision if identity is not None else "")
                     or (_sha16(identity_text) if identity_text else "")),
        "self_model": (plan.self_model.revision
                       if plan.self_model is not None else ""),
        "lessons": (sha12(lessons_rev) if lessons_rev else ""),
        "samples_library": sample_rev,
        "response_plan": (str(plan_ref.revision)
                          if plan_ref is not None and plan_ref.revision
                          else (sha12(plan_ref.text)
                                if plan_ref is not None and plan_ref.text
                                else "")),
        # ADD-EXP: ревизия слоя «Выражение» (рендер) и набора примеров —
        # «present с ревизией» без expression_absent при активном режиме.
        "expression": (str(expr_trace.revision) if expr_trace is not None
                       else ""),
        "expression_examples": (
            str(expr_examples_trace.revision)
            if expr_examples_trace is not None else ""),
        "channel": f"{profile}/{plan.channel}/"
                   f"{'html' if plan.html_safe else 'text'}/{sha12(base_text)}",
        "composer": "w2",
    }


def _manifest_id(system: str, user_parts: Sequence[str],
                 versions: Mapping[str, str]) -> str:
    material = "\x1e".join((
        str(system or ""),
        "\x1f".join(str(p or "") for p in (user_parts or ())),
        json.dumps(dict(versions or {}), sort_keys=True, ensure_ascii=False),
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _remember(manifest: PromptManifest) -> None:
    key = (int(manifest.chat_id or 0), str(manifest.run_id or "-"),
           str(manifest.writer or ""))
    with _manifest_lock:
        _manifests[key] = manifest
        while len(_manifests) > MANIFEST_CACHE_MAX:
            _manifests.popitem(last=False)
        last_key = (int(manifest.chat_id or 0), str(manifest.writer or ""))
        layers = {t.layer: (t.revision, t.chars, t.rendered, t.skip_reason)
                  for t in manifest.layers}
        previous = _last_layers.get(last_key)
        if previous is not None:
            prev_id, prev_layers, prev_tokens = previous
            if prev_id != manifest.manifest_id:
                changed = [layer for layer in sorted(set(prev_layers)
                                                      | set(layers))
                           if prev_layers.get(layer) != layers.get(layer)]
                _diffs[manifest.manifest_id] = {
                    "previous_manifest_id": prev_id,
                    "changed_layers": changed,
                    "tokens_delta": (int(manifest.tokens_total or 0)
                                     - int(prev_tokens or 0)),
                }
                while len(_diffs) > MANIFEST_CACHE_MAX:
                    _diffs.popitem(last=False)
        _last_layers[last_key] = (manifest.manifest_id, layers,
                                  int(manifest.tokens_total or 0))
        while len(_last_layers) > MANIFEST_CACHE_MAX:
            _last_layers.popitem(last=False)


def _fallback_manifest(plan: PromptPlan) -> PromptManifest:
    """Последний рубеж: композер никогда не бросает."""
    base = str(plan.base_prompt or "")
    trace = _trace(LAYER_CHANNEL_CONTRACT, block_id="channel_canon",
                   text=base, owner="channel",
                   source=str(plan.base_source or "default"),
                   revision=sha12(base), rendered=bool(base.strip()),
                   skip_reason="compose_error")
    versions = {"composer": "w2", "channel": sha12(base)}
    return PromptManifest(
        system=base,
        user_parts=tuple(str(p) for p in (plan.user_parts or ())),
        layers=(trace,),
        versions=versions,
        flags={},
        conflicts=(),
        manifest_id=_manifest_id(base, plan.user_parts or (), versions),
        profile=str(plan.profile or ""),
        writer=str(plan.writer or ""),
        chat_id=int(plan.chat_id or 0),
        run_id=(str(plan.run_id) if plan.run_id else None),
        tokens_total=estimate_tokens(base),
    )


def compose_prompt(plan: PromptPlan) -> PromptManifest:
    """Собрать system/user + трассу слоёв. Никогда не бросает (§2 правило 1)."""
    try:
        return _compose(plan)
    except Exception:
        logger.warning("[composer] compose failed — fail-open (channel only)",
                       exc_info=True)
        try:
            manifest = _fallback_manifest(plan)
            emit_layer_events(manifest)
            return manifest
        except Exception:      # pragma: no cover — защитная ветка
            return PromptManifest(system=str(plan.base_prompt or ""))


def compose_machine_system(base_prompt: str, *, writer: str,
                           chat_id: int = 0, run_id: str | None = None,
                           base_source: str = "default") -> PromptManifest:
    """Профиль ``machine_json``: только канал-контракт (§2.2).

    Тот же владелец сборки для машинных стадий (L1/Stage-1/factcheck/...):
    Core и юмор физически не подключаются, байты базы не меняются.
    """
    return compose_prompt(PromptPlan(
        profile=PROFILE_MACHINE_JSON, writer=str(writer or ""),
        chat_id=int(chat_id or 0), run_id=run_id,
        base_prompt=str(base_prompt or ""), base_source=base_source))


# ═════════════════════════════════════════════════════════════════════════════
# INS-TRACE / INS-EXACT: журнал РЕАЛЬНЫХ provider-вызовов
# ═════════════════════════════════════════════════════════════════════════════


def sha256_text(text: Any) -> str:
    """sha256 произвольного текста (payload/сообщения)."""
    value = "" if text is None else str(text)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def payload_checksum(payload: Any) -> str:
    """sha256 канонического JSON фактически отправленного payload.

    Канонизация (``sort_keys`` + компактные сепараторы) не зависит от порядка
    ключей в памяти, но полностью определяется значениями: два разных тела
    запроса не дадут одинаковый хеш.
    """
    try:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str)
    except Exception:       # pragma: no cover — защитная ветка
        body = str(payload)
    return sha256_text(body)


def messages_checksum(messages: Sequence[Mapping[str, Any]]) -> str:
    """sha256 канонического списка сообщений (role+content, порядок важен)."""
    norm = [{"role": str(m.get("role") or ""),
             "content": str(m.get("content") or "")}
            for m in (messages or ()) if isinstance(m, Mapping)]
    return payload_checksum(norm)


def _redact_chat_id(chat_id: Any) -> dict:
    """chat_id с privacy-redaction (INS-TRACE): raw не отдаётся наружу."""
    try:
        value = int(chat_id or 0)
    except (TypeError, ValueError):
        value = 0
    text = str(value)
    if len(text) <= 4:
        masked = text
    elif len(text) <= 7:
        masked = text[:2] + "*" * (len(text) - 3) + text[-1]
    else:
        masked = text[:2] + "*" * (len(text) - 4) + text[-2:]
    return {"chat_id_redacted": masked,
            "chat_sha12": sha256_text(text)[:12]}


def record_provider_call(*, payload: Any, messages: Sequence[Mapping[str, Any]],
                         model: str = "", provider: str = "",
                         module: str = "", step: str = "",
                         correlation_id: str = "", chat_id: Any = None,
                         channel: str = "primary", status: str = "ok",
                         error: str = "") -> dict:
    """Зафиксировать РЕАЛЬНЫЙ вызов провайдера (INS-TRACE/INS-EXACT).

    ``payload`` — ровно то тело, что ушло в HTTP (после adapt/fallback);
    ``messages`` — те же сообщения (system+user, порядок как в запросе).
    Текст обязан приходить уже санитизированным вызывающим (``llm_client``
    маскирует секреты каноническим маскером) — журнал R17-safe. Хеши
    считаются по фактическим байтам содержимого и остаются доказательством,
    даже если длинный текст усечён для памяти.

    Никогда не бросает: диагностика не должна ломать вызов модели.
    """
    try:
        checksum = payload_checksum(payload)
        parts: list[dict] = []
        for msg in (messages or ()):
            if not isinstance(msg, Mapping):
                continue
            content = str(msg.get("content") or "")
            truncated = len(content) > _PROVIDER_TEXT_MAX
            parts.append({
                "role": str(msg.get("role") or ""),
                "chars": len(content),
                "sha256": sha256_text(content),
                "truncated": bool(truncated),
                "text": (content[:_PROVIDER_TEXT_MAX] + "…"
                         if truncated else content),
            })
        system_text = next((p["text"] for p in parts
                            if p["role"] == "system"), "")
        entry = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "correlation_id": str(correlation_id or ""),
            "manifest_checksum": checksum,
            "checksum_algo": "sha256",
            "messages_checksum": messages_checksum(messages),
            "model": str(model or ""),
            "provider": str(provider or ""),
            "module": str(module or ""),
            "step": str(step or ""),
            "channel": str(channel or "primary"),
            "status": str(status or "ok"),
            "error": str(error or ""),
            "message_count": len(parts),
            "roles": [p["role"] for p in parts],
            "chars_total": sum(p["chars"] for p in parts),
            "messages": parts,
            "system": system_text,
            "system_chars": len(system_text),
            "system_sha256": sha256_text(system_text),
        }
        entry.update(_redact_chat_id(chat_id))
        with _provider_lock:
            key = "%s:%d" % (checksum[:16], next(_provider_seq))
            _provider_calls[key] = entry
            while len(_provider_calls) > PROVIDER_CALL_MAX:
                _provider_calls.popitem(last=False)
        return dict(entry)
    except Exception:       # pragma: no cover — защитная ветка
        logger.warning("[composer] provider trace failed — fail-open",
                       exc_info=True)
        return {}


def provider_calls(*, chat_id: Any = None, limit: int = 10,
                   module: str = "", status: str = "") -> list[dict]:
    """Последние реальные вызовы (новые → старые), фильтр по чату/этапу."""
    try:
        key_chat = int(chat_id or 0) if chat_id is not None else None
    except (TypeError, ValueError):
        key_chat = None
    out: list[dict] = []
    with _provider_lock:
        items = list(reversed(_provider_calls.values()))
    for entry in items:
        if module and str(entry.get("module") or "") != module:
            continue
        if status and str(entry.get("status") or "") != status:
            continue
        if key_chat is not None:
            raw = entry.get("chat_id_redacted") or ""
            # Точная привязка к чату — по хешу, а не по маске.
            if entry.get("chat_sha12") != sha256_text(key_chat)[:12]:
                continue
        out.append(dict(entry))
        if len(out) >= max(1, int(limit or 1)):
            break
    return out


def last_provider_call(*, chat_id: Any = None, module: str = "") -> dict | None:
    """Самый свежий реальный вызов (для «last actual request» в Inspector)."""
    calls = provider_calls(chat_id=chat_id, module=module, limit=1)
    return calls[0] if calls else None


def reset_provider_calls() -> None:
    """Очистить журнал вызовов (тесты/диагностика)."""
    with _provider_lock:
        _provider_calls.clear()


def render_layer_texts(manifest: PromptManifest) -> dict:
    """Текст каждого включённого блока манифеста (owner-debug, INS-HIERARCHY).

    Отдельный API, а не поле ``render_effective_layers``: провенанс-события и
    телеметрия остаются без сырого текста. Вызывать только из owner-gated
    поверхностей (Inspector).
    """
    rows = []
    for trace in manifest.layers:
        rows.append({
            "layer": trace.layer,
            "label": layer_label(trace.layer),
            "block_id": trace.block_id,
            "owner": trace.owner,
            "source": trace.source,
            "revision": trace.revision,
            "chars": trace.chars,
            "rendered": trace.rendered,
            "skip_reason": trace.skip_reason,
            "skip_reason_human": skip_reason_label(trace.skip_reason),
            "detail": trace.detail,
            "text": trace.text if trace.rendered else "",
        })
    return {"manifest_id": manifest.manifest_id, "layers": rows}


#: INS-TRACE: какие реальные каналы попадают в bounded-журнал, а какие — нет
#: (с причиной). Отсутствие канала не выдаётся за «покрыто всё».
PROVIDER_TRACE_COVERAGE: tuple[Mapping[str, Any], ...] = (
    {"channel": "generate", "covered": True,
     "reason": "LLMClient.generate: чат-ответы, L1/L2, Stage-1/2, tool-phase"},
    {"channel": "generate_chat", "covered": True,
     "reason": "LLMClient.generate_chat: реальные tool-calling вызовы"},
    {"channel": "generate_background", "covered": True,
     "reason": "LLMClient.generate_background: фоновые батчи"},
    {"channel": "generate_worker", "covered": True,
     "reason": "LLMClient.generate_worker: выделенные роли воркеров"},
    {"channel": "stream_chat_completion", "covered": True,
     "reason": ("SSE-стрим фиксируется при успешном завершении; ошибки "
                "стрима классифицируются существующими LLM*-исключениями")},
    {"channel": "embed", "covered": False,
     "reason": ("эмбеддинги не формируют «итоговый промпт» (контракт "
                "input/vectors, без messages) — в журнал вызовов модели "
                "не входят")},
)


def trace_coverage() -> list[dict]:
    """Что реально трассируется (INS-TRACE), без молчаливых пропусков."""
    return [dict(row) for row in PROVIDER_TRACE_COVERAGE]


# ═════════════════════════════════════════════════════════════════════════════
# «Покажи effective layers» + R17-safe события
# ═════════════════════════════════════════════════════════════════════════════

def render_effective_layers(manifest: PromptManifest) -> dict:
    """Публичный API эффективных слоёв (§2 правило 3).

    Отдаёт порядок слоёв, источник/ревизию/причину/конфликт, Σ токенов и
    разницу с прошлым манифестом того же (chat, writer). Сырого текста тут
    нет — только провенанс и размеры.
    """
    layers = []
    for trace in manifest.layers:
        layers.append({
            "layer": trace.layer,
            "block_id": trace.block_id,
            "owner": trace.owner,
            "source": trace.source,
            "revision": trace.revision,
            "chars": trace.chars,
            "tokens": trace.tokens,
            "rendered": trace.rendered,
            "skip_reason": trace.skip_reason,
            "conflict": trace.conflict,
            "detail": trace.detail,
        })
    order = [t.layer for t in manifest.layers]
    unique_order = list(dict.fromkeys(order))
    canonical_subset = [lay for lay in LAYER_ORDER if lay in set(order)]
    grouped = all(
        order.index(lay) + order.count(lay) ==
        len(order) - order[::-1].index(lay) for lay in unique_order)
    conflict_ids = list(dict.fromkeys(
        [t.conflict for t in manifest.layers if t.conflict]
        + [c.conflict_id for c in manifest.conflicts]))
    out = {
        "manifest_id": manifest.manifest_id,
        "profile": manifest.profile,
        "writer": manifest.writer,
        "layer_order": order,
        "layers_in_priority_order": unique_order,
        "canonical_order": list(LAYER_ORDER),
        "order_matches_canonical": bool(unique_order == canonical_subset
                                        and grouped),
        "layers": layers,
        "tokens_total": int(manifest.tokens_total or 0),
        "versions": dict(manifest.versions or {}),
        "flags": dict(manifest.flags or {}),
        "conflicts": [dataclasses.asdict(c) for c in manifest.conflicts],
        "conflict_ids": conflict_ids,
        "rendered_layers": [t.layer for t in manifest.layers if t.rendered],
        "skipped_layers": [t.layer for t in manifest.layers
                           if not t.rendered],
        "diff_vs_previous": _diff_vs_previous(manifest),
    }
    return out


def _diff_vs_previous(manifest: PromptManifest) -> dict | None:
    """Разница с предыдущим манифестом того же (chat, writer), по manifest_id."""
    with _manifest_lock:
        diff = _diffs.get(manifest.manifest_id)
    return dict(diff) if diff else None


def manifest_for_events(manifest: PromptManifest) -> dict:
    """R17-safe представление манифеста (только трасса/версии, §2 правило 4)."""
    return {
        "manifest_id": manifest.manifest_id,
        "profile": manifest.profile,
        "writer": manifest.writer,
        "chat_id": int(manifest.chat_id or 0),
        "run_id": manifest.run_id,
        "tokens_total": int(manifest.tokens_total or 0),
        "versions": dict(manifest.versions or {}),
        "flags": dict(manifest.flags or {}),
        "layers": [{
            "layer": t.layer,
            "block_id": t.block_id,
            "owner": t.owner,
            "source": t.source,
            "revision": t.revision,
            "chars": t.chars,
            "tokens": t.tokens,
            "rendered": t.rendered,
            "skip_reason": t.skip_reason,
            "conflict": t.conflict,
            "detail": t.detail,
        } for t in manifest.layers],
        "conflict_ids": [c.conflict_id for c in manifest.conflicts],
    }


def emit_layer_events(manifest: PromptManifest, *,
                      chat_id: int | None = None) -> list[dict]:
    """Notable-события деградации: причина видима, спама нет (SOUL-15.7).

    Одно событие на (chat, layer, reason) за процесс (bounded LRU);
    никакого текста промпта в полях — R17-safe.
    """
    emitted: list[dict] = []
    target_chat = int(manifest.chat_id or 0) if chat_id is None \
        else int(chat_id or 0)
    for trace in manifest.layers:
        reason = trace.skip_reason
        if not reason:
            continue
        status = f"{trace.layer}:{reason}"
        dedup_key = (target_chat, status)
        with _event_lock:
            if dedup_key in _emitted_reasons:
                continue
            _emitted_reasons[dedup_key] = None
            while len(_emitted_reasons) > _EVENT_DEDUP_MAX:
                _emitted_reasons.popitem(last=False)
        if reason in _ERROR_REASONS:
            outcome, level, code = "failed", "WARN", "source_missing"
        elif reason in _OFF_REASONS:
            outcome, level, code = "skipped", "INFO", "disabled"
        elif reason in ("profile:machine_stage", "profile:editorial_eligibility",
                        "profile:internal_silent"):
            outcome, level, code = "silent", "INFO", "disabled"
        else:
            outcome, level, code = "silent", "INFO", "source_missing"
        try:
            from services import mca_events
            event = mca_events.emit_mca_event(
                "prompt_layers", outcome=outcome, level=level,
                component="prompt_composer", stage="compose", status=status,
                chat_id=target_chat, reason_code=code)
        except Exception:      # pragma: no cover — fail-open
            event = None
        if event is not None:
            emitted.append(event)
        # ADD-EXP §6: класс `composer_excluded` — режим «Выражения» разрешён,
        # но слой не рендерен/вытеснен. Отдельная точка диагностики (свой
        # дедуп в `mca_expression`), событие prompt_layers не заменяет.
        if trace.layer == LAYER_EXPRESSION and reason in (
                "expression_absent", "expression_disabled"):
            try:
                from services import mca_expression as _expr
                _expr.emit_expression_diag(
                    "composer_excluded", chat_id=target_chat,
                    stage="compose", detail=reason)
            except Exception:      # pragma: no cover — fail-open
                pass
    return emitted


def emit_layer_events_once(manifest: PromptManifest) -> list:
    """Хелпер для вызывающих: эмиссия без исключений и без дублей."""
    try:
        return emit_layer_events(manifest)
    except Exception:          # pragma: no cover — fail-open
        return []
