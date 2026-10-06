"""MCA-18 `mca-18-self-model` — SelfModelSnapshot, три настройки, субъект
памяти и запреты (ADR-1028-18 D1/D2/D4; §28.2 `:1513–1527`,
§28.3 `:1529–1546`).

Один модуль (БЕЗ отдельного сервиса/провайдера — D1): snapshot + резолвер +
атрибуция/запреты. Второй механизм личности НЕ создаётся: хранение —
существующее (PG `personas`, флаги, graph_facts + v31-расширение контракта
mca-03/04a); вставка характера — только швы mca-08 (блок C, T-5081).

Инварианты:
* (I-1) один snapshot на запуск ответа; `version` — производный токен
  (persona_version + rules_version + flags_revision), в trace (блок C).
* (I-2) `agent_id`/`persona_version` НЕ меняются от смены модели/токена:
  persona_version = хеш СОДЕРЖИМОГО персоны (name/biography/overrides/
  is_aware_ai/updated_at); смена Telegram-аккаунта — явный rebind.
* (I-3) capabilities ≠ вымысел: из реестра инструментов/runtime, не из
  биографии; «могу» ≠ «посмотрел» (нужен успешный анализ) ≠ «помню всё»
  (память ограничена доступной областью).
* Три состояния настройки (`False` / `null-наследовать` / `ошибка`) —
  разные резолвы; ошибка НИКОГДА не сворачивается в False (D2).
* OFF persona ≠ отмена авторства: agent_id/bot_user_id/атрибуция живут
  независимо от `persona_enabled` (§28.2 `:1521`).
* Запреты §28.3 `:1535–1544` enforced guard-функциями до записи/компиляции;
  «в чате принято X» ≠ «я предпочитаю X» — позиции только через
  `mca_adoption_links` с основаниями (D4).

R17: в событиях/логах — только ID/коды/enum/числа/refs; сырые тексты
памяти НЕ системные инструкции (GEN-R18).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass

from services import mca_events, mca_gates

logger = logging.getLogger(__name__)

SELF_MODEL_VERSION = "mca18-self-1"

PERSONA_ENABLED_KEY = "flags.persona_enabled"
SELF_AWARENESS_KEY = "flags.bot_self_awareness_enabled"

# ── закрытые наборы контракта (spec §8.1, DDL v31 CHECK) ────────────────────
PERSPECTIVES = frozenset({
    "self", "other", "quoted", "third_party", "ambiguous"})
MEMORY_KINDS = frozenset({
    "world_fact", "self_event", "self_trait", "opinion", "belief",
    "paradigm", "mood", "lesson"})
MEMORY_SCOPES = frozenset({"global", "chat"})
SUBJECT_STATUSES = frozenset({"self", "ambiguous", "other"})
RULE_STATUSES = frozenset({
    "observed", "candidate", "active", "rejected", "suspended", "superseded"})

# Режим самопредставления (§28.2 `:1522`): ролевое поведение, не онтология.
MODE_AWARE = "aware"
MODE_IN_CHARACTER = "in_character"

# Источники наследования настройки (прецедент gate-resolver mca-06).
SOURCE_CHAT = "chat"
SOURCE_GLOBAL = "global"
SOURCE_DEFAULT = "default"
SOURCE_ERROR = "error"


class SelfModelDisabled(RuntimeError):
    """K1 `MCA_SELF_MODEL_ENABLED` OFF — SelfModel-контур не выполняется
    (legacy-путь `build_persona_prompt_block` как 2.58.61)."""


class SelfModelSnapshotError(RuntimeError):
    """Ошибка сборки snapshot (идентичность/PG) — честный отказ, НИКОГДА
    не маскируется пустой персоной (D2; reason `self_model_snapshot_error`)."""


# ═══ D2: три независимые настройки — одна семантика резолва ═════════════════

@dataclass(frozen=True)
class SettingState:
    """Резолв одной настройки: `False` / `None`-наследовать / ошибка —
    ТРИ разных состояния (D2); effective + источник наследования."""

    key: str
    value: bool | None          # None = null/наследовать (или ошибка)
    source: str                 # chat | global | default | error
    error: str | None = None    # R17: только тип ошибки, без содержимого

    @property
    def is_error(self) -> bool:
        return self.source == SOURCE_ERROR

    def effective(self, default: bool = True) -> bool:
        """Effective-значение (None → default). Ошибка НЕ сворачивается в
        False на этом уровне: вызывающий видит `is_error` и решает честно."""
        if self.is_error:
            return bool(default)
        return bool(self.value) if self.value is not None else bool(default)


async def resolve_persona_enabled(chat_id: int | None) -> SettingState:
    """`flags.persona_enabled` (per-chat override → global hot → env).
    OFF ≠ отмена авторства/тех-идентичности (D2)."""
    return await _resolve_flag_param(
        chat_id, PERSONA_ENABLED_KEY, "PERSONA_ENABLED")


async def resolve_bot_self_awareness(chat_id: int | None) -> SettingState:
    """`flags.bot_self_awareness_enabled` — рефлексия собственных ответов
    (существующий flags-путь `direct_chat_service.py:4857–4861`)."""
    return await _resolve_flag_param(
        chat_id, SELF_AWARENESS_KEY, "BOT_SELF_AWARENESS_ENABLED")


async def _resolve_flag_param(chat_id: int | None, key: str,
                              env_default: str) -> SettingState:
    """Общий резолв параметра-флага с источником наследования.
    Ошибка → source='error' (не маскируется); R17: error = тип исключения."""
    try:
        from config.settings import settings
        from services import chat_params
        from services import hot_config as hot
        default = bool(getattr(settings, env_default, True))
        source = SOURCE_DEFAULT
        if chat_id is None:
            raw = hot.get(key, default)
        else:
            # Корневой лейаут чата (module-level, fail-open) — только для
            # ОПРЕДЕЛЕНИЯ источника наследования; значение резолвит
            # `get_chat_param` (единый механизм mca-06-прецедента).
            root = await chat_params.get_all_chat_params(int(chat_id))
            overrides = (root or {}).get("overrides") or {}
            if key in overrides:
                source = SOURCE_CHAT
            if source != SOURCE_CHAT and hot.get(key, None) is not None:
                source = SOURCE_GLOBAL
            raw = await chat_params.get_chat_param(int(chat_id), key, default)
        return SettingState(key=key, value=bool(raw), source=source)
    except Exception as exc:                       # честный error-state
        logger.warning("[mca18] flag resolve failed | key=%s | %s",
                       key, type(exc).__name__)
        return SettingState(key=key, value=None, source=SOURCE_ERROR,
                            error=type(exc).__name__)


async def resolve_is_aware_ai(chat_id: int | None) -> SettingState:
    """`personas.is_aware_ai` (PG; БЕЗ изменения схемы): chat-строка →
    global-строка → null-наследовать; PG недоступен/ошибка — отдельное
    состояние (не False, не null). REUSE SQL `bot_persona` (один контракт)."""
    from services import bot_persona
    pool = bot_persona._persona_pool()
    if pool is None:
        return SettingState(key="personas.is_aware_ai", value=None,
                            source=SOURCE_ERROR, error="pg_unavailable")
    try:
        async with pool.acquire() as conn:
            if chat_id is not None:
                row = await conn.fetchrow(bot_persona._SELECT_CHAT_SQL,
                                          int(chat_id))
                if row is not None:
                    return SettingState(key="personas.is_aware_ai",
                                        value=bool(row.get("is_aware_ai",
                                                           True)),
                                        source=SOURCE_CHAT)
            row = await conn.fetchrow(bot_persona._SELECT_GLOBAL_SQL)
            if row is not None:
                return SettingState(key="personas.is_aware_ai",
                                    value=bool(row.get("is_aware_ai", True)),
                                    source=SOURCE_GLOBAL)
    except Exception as exc:
        logger.warning("[mca18] is_aware_ai resolve failed | chat=%s | %s",
                       chat_id, type(exc).__name__)
        return SettingState(key="personas.is_aware_ai", value=None,
                            source=SOURCE_ERROR, error=type(exc).__name__)
    return SettingState(key="personas.is_aware_ai", value=None,
                        source=SOURCE_DEFAULT)


# ═══ T-5076: техническая идентичность — из реестра инструментов ═════════════

@dataclass(frozen=True)
class Capabilities:
    """Runtime-возможности/ограничения (§28.2 `:1527`): источник — реестр
    инструментов + runtime-состояние, НЕ биография.

    «могу посмотреть изображение» — только при работающем vision-пути;
    «посмотрел» — только после успешного анализа конкретного asset
    (`did_analyze_images`, инжектируется runtime-доказательством);
    «помню» привязано к доступной памяти (`memory_scope`), не ко всему
    архиву."""

    tool_names: tuple[str, ...]
    can_analyze_images: bool = False     # до mca-19 — честный False
    did_analyze_images: bool = False     # только runtime-доказательство
    memory_scope: str = "accessible_memory"
    source: str = "tool_registry"

    @property
    def can_remember_everything(self) -> bool:
        """«Помню всё» — всегда False (запрет `:1527`)."""
        return False


# Имена инструментов, дающих анализ изображений. До mca-19 реестр таких не
# объявляет — честный False (инвариант I-3: нет vision → не заявляем).
# MCA-19 (ADR-1028-19 D14/§8.10): источник «могу» — НЕ реестр (инструмент
# `recognize_image` ≠ доказательство работающего vision-маршрута), а ЕДИНЫЙ
# сервис mca-19 (`resolve_effective_state`): requested ∧ capability ok.
# Реестровый путь остаётся пустым — делегация ниже единственный источник True.
IMAGE_ANALYSIS_TOOL_NAMES: frozenset[str] = frozenset()


async def can_analyze_images_effective(chat_id: int | None = None) -> bool:
    """MCA-19 (ADR-1028-19 D14, §8.10): владелец флага `can_analyze_images`
    — mca-19. Делегация в ЕДИНЫЙ сервис: True ⇔ requested-ON ∧ пройденный
    capability-чек (`effective_enabled`). K1/env-мастер OFF → немедленно
    False (бит-в-бит 2.58.62); pending/ошибка → False (честно: «могу» ≠
    «не проверено»). Никогда не бросает."""
    try:
        from services import mca_gates as _gates
        if not _gates.vision_enabled():
            return False
        from services.mca_vision import resolve_effective_state
        state = await resolve_effective_state(chat_id)
        return bool(state.effective_enabled)
    except Exception:
        logger.warning("[mca18] can_analyze_images delegation failed",
                       exc_info=True)
        return False


def build_capabilities(*, image_analysis_evidence: bool | None = None,
                       can_analyze_images: bool | None = None
                       ) -> Capabilities:
    """Capabilities из `tool_schemas.active_tools()` (реестр + env-гейты);
    `image_analysis_evidence` — ТОЛЬКО runtime-доказательство успешного
    анализа (не биография/настройка).
    MCA-19 (ADR-1028-19 D14): `can_analyze_images` — результат делегации
    `can_analyze_images_effective()` (вызывает async-контекст); None →
    прежний реестровый путь (сейчас всегда False, бит-в-бит)."""
    try:
        from services import tool_schemas
        names = tuple(sorted(
            t["function"]["name"] for t in tool_schemas.active_tools()))
    except Exception:
        logger.warning("[mca18] capabilities read failed", exc_info=True)
        names = ()
    if can_analyze_images is None:
        can_images = bool(IMAGE_ANALYSIS_TOOL_NAMES & set(names))
    else:
        can_images = bool(can_analyze_images)
    did_images = bool(can_images and image_analysis_evidence)
    return Capabilities(tool_names=names, can_analyze_images=can_images,
                        did_analyze_images=did_images)


def capability_claim_allowed(claim: str, caps: Capabilities) -> bool:
    """Проверка заявления о себе (§28.2 `:1527`): «могу» ≠ «посмотрел» ≠
    «помню всё». Канон заявлений — фиксированный набор; остальное False."""
    if caps is None:
        return False
    if claim == "analyze_image":
        return bool(caps.can_analyze_images)
    if claim == "image_analyzed":
        return bool(caps.did_analyze_images)
    if claim == "remember_everything":
        return False
    if claim == "use_tools":
        return bool(caps.tool_names)
    return False


# ═══ D1: SelfModelSnapshot ══════════════════════════════════════════════════

@dataclass(frozen=True)
class TraitView:
    """Компилированное view активного BehaviorRule (read-side; lifecycle —
    блок C). Self-trait применим только в рамках applicability (запрет
    «всем темам/адресатам» — T-5078)."""

    rule_id: int
    dimension: str
    target_value: float | None
    strength: float | None
    scope: str | None
    applicability: tuple[str, ...]
    exclusions: tuple[str, ...]
    version: int
    excluded_reason: str | None = None

    @property
    def included(self) -> bool:
        return self.excluded_reason is None


@dataclass(frozen=True)
class Position:
    """Собственное мнение С provenance (D4): существует только через
    adoption-связь с основаниями и временем."""

    opinion_ref: str
    text: str
    basis_refs: tuple[str, ...]
    adopted_at: int


@dataclass(frozen=True)
class MoodState:
    """Настроение — обратимая поправка с временем окончания (TTL; запрет
    «необратимо менять личность», §28.3 `:1543`)."""

    text: str
    fact_id: int
    valid_to: int

    @property
    def expired(self) -> bool:
        return int(time.time()) >= self.valid_to


@dataclass(frozen=True)
class SelfModelSnapshot:
    """Снимок модели себя на запуск ответа (frozen; не хранимая сущность).
    Поля §28.2 `:1517`. Один snapshot на запуск (I-1)."""

    agent_id: str
    bot_user_id: int | None
    identity_binding: str            # bound | runtime | unbound
    persona_id: str | None           # PG-строка (name как естественный id)
    persona_version: str             # хеш СОДЕРЖИМОГО (I-2: модель/токен ≠)
    scope_chat_id: int | None
    name: str
    aliases: tuple[str, ...]         # display-алиасы (REUSE mca-03); без
                                     # фабрикации — пусто, если нет данных
    biography: str
    style_version: str | None        # хеш system_prompt_overrides
    traits: tuple[TraitView, ...]
    interests: tuple[str, ...]
    relations: tuple[str, ...]       # локальны по chat (§28.4 `:1584`)
    state: MoodState | None
    positions: tuple[Position, ...]
    persona_enabled: SettingState
    is_aware_ai: SettingState
    bot_self_awareness: SettingState
    self_presentation_mode: str      # aware | in_character
    capabilities: Capabilities
    rules_status: str                # on | disabled | error (K2-ось)
    version: str                     # производный токен (I-1/trace)
    created_at: int
    # ── T-5088 (fallback, §28.5 `:1576`): маркеры деградации. НЕ входят в
    # `version` (идентичность ≠ деградация); fallback никогда не репортится
    # как «успешно загруженная персона».
    stale: bool = False              # last-known-good вне live-чтения
    fallback: str = ""               # "" | "lkg" | "minimal"

    @property
    def persona_is_empty(self) -> bool:
        """Пустая персона (A58): различимое поведение, не пустая строка."""
        return not (self.name or self.biography or self.traits
                    or self.positions)

    @property
    def authorship(self) -> dict:
        """Авторство — НЕ зависит от persona_enabled (OFF persona ≠ отмена
        авторства, `:1521`)."""
        return {
            "agent_id": self.agent_id,
            "bot_user_id": self.bot_user_id,
            "scope_chat_id": self.scope_chat_id,
        }


def persona_version_hash(*, name: str = "", biography: str = "",
                         overrides: str = "", is_aware_ai: bool = True,
                         updated_at: str | None = None) -> str:
    """Хеш СОДЕРЖИМОГО персоны (R2d): модель/токен/bot_user_id НЕ входят —
    смена провайдера не создаёт новую личность (I-2)."""
    material = "\x1f".join((
        "v1", str(name or ""), str(biography or ""), str(overrides or ""),
        "1" if is_aware_ai else "0", str(updated_at or "")))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def style_version_hash(overrides: str) -> str | None:
    """`style_version` = хеш `system_prompt_overrides` (пусто → None)."""
    text = str(overrides or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _snapshot_version(*, agent_id: str, persona_version: str,
                      persona_enabled: SettingState,
                      is_aware_ai: SettingState,
                      bot_self_awareness: SettingState,
                      rules_version: str, scope_chat_id: int | None) -> str:
    """Производный токен snapshot (кеш-прецедент
    `mca_retrieval_context.compute_context_version:257`)."""
    material = "\x1f".join((
        SELF_MODEL_VERSION, agent_id, persona_version,
        f"persona_enabled={persona_enabled.source}:{persona_enabled.value}",
        f"aware={is_aware_ai.source}:{is_aware_ai.value}",
        f"reflection={bot_self_awareness.source}:{bot_self_awareness.value}",
        f"rules={rules_version}",
        f"scope={scope_chat_id or 'global'}"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _rules_version(rules: tuple[TraitView, ...]) -> str:
    if not rules:
        return "0"
    tail = max((r.rule_id for r in rules), default=0)
    return f"{len(rules)}:{tail}"


def _flags_revision(persona_enabled: SettingState, is_aware_ai: SettingState,
                    bot_self_awareness: SettingState) -> str:
    return hashlib.sha256("\x1e".join((
        f"{persona_enabled.source}:{persona_enabled.value}",
        f"{is_aware_ai.source}:{is_aware_ai.value}",
        f"{bot_self_awareness.source}:{bot_self_awareness.value}",
    )).encode("utf-8")).hexdigest()[:12]


def _tuple_from_json(raw) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(x) for x in raw if str(x).strip())
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return ()
    if isinstance(parsed, (list, tuple)):
        return tuple(str(x) for x in parsed if str(x).strip())
    return ()


async def resolve_self_model(db, scope_chat_id: int | None = None, *,
                             bot_user_id: int | None = None,
                             now: int | None = None) -> SelfModelSnapshot:
    """`resolve_self_model(scope)` (D6): один snapshot на запуск.

    K1 OFF → `SelfModelDisabled` (legacy-путь; никаких чтений v31).
    Ошибка идентичности → `SelfModelSnapshotError` + событие (не маскируется).
    `bot_user_id` — фактический runtime (get_me); если передан и отличается
    от явного binding — snapshot помечает `identity_binding='runtime'`
    (rebind — только явное admin-действие, не по похожему имени)."""
    if not mca_gates.self_model_enabled():
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="resolve", reason_code="self_model_disabled",
            status="disabled")
        raise SelfModelDisabled(
            "self_model disabled (MCA_SELF_MODEL_ENABLED=OFF)")
    ts = int(now if now is not None else time.time())
    try:
        identity = await db.get_self_identity()
    except Exception as exc:                       # честный отказ
        mca_events.emit_mca_event(
            "self_model", outcome="failed", level="ERROR",
            component="self_model", stage="resolve",
            reason_code="self_model_snapshot_error",
            chat_id=scope_chat_id, status="identity_read_failed")
        raise SelfModelSnapshotError(
            f"self identity read failed: {type(exc).__name__}") from exc
    if not identity or not identity.get("agent_id"):
        mca_events.emit_mca_event(
            "self_model", outcome="failed", level="ERROR",
            component="self_model", stage="resolve",
            reason_code="self_model_snapshot_error",
            chat_id=scope_chat_id, status="identity_missing")
        raise SelfModelSnapshotError("self identity missing (v31 seed)")
    agent_id = str(identity["agent_id"])
    bound_user_id = identity.get("bot_user_id")
    if bot_user_id is not None and bound_user_id is not None \
            and int(bot_user_id) != int(bound_user_id):
        binding = "runtime"      # расхождение видимо; rebind — явное действие
        effective_user_id = int(bot_user_id)
    elif bot_user_id is not None:
        binding = "runtime"
        effective_user_id = int(bot_user_id)
    elif bound_user_id is not None:
        binding = "bound"
        effective_user_id = int(bound_user_id)
    else:
        binding = "unbound"
        effective_user_id = None

    # Персона (REUSE `bot_persona.resolve_bot_persona`: chat → global → empty).
    from services import bot_persona
    try:
        persona = await bot_persona.resolve_bot_persona(scope_chat_id)
    except Exception:
        persona = bot_persona.BotPersona.empty()
    aware_state = await resolve_is_aware_ai(scope_chat_id)
    persona_enabled = await resolve_persona_enabled(scope_chat_id)
    reflection = await resolve_bot_self_awareness(scope_chat_id)

    # Черты/состояние/позиции (v31; K2 OFF → честный disabled, таблицы
    # инертны — T-5078 read-side работает только при ON).
    if mca_gates.trait_rules_enabled():
        try:
            rule_rows = await db.list_behavior_rules(agent_id, "active")
            rules_status = "on"
        except Exception:
            rule_rows = []
            rules_status = "error"
        mood_row = await _latest_mood_row(db, agent_id, scope_chat_id, ts)
    else:
        rule_rows = []
        rules_status = "disabled"
        mood_row = None

    traits = tuple(_compile_trait_view(r) for r in (rule_rows or []))
    mood = None
    if mood_row is not None:
        mood = MoodState(text=str(mood_row.get("fact") or "")[:200],
                         fact_id=int(mood_row["id"]),
                         valid_to=int(mood_row.get("valid_to") or 0))

    try:
        adoption_rows = await db.list_adoption_links(agent_id)
        positions = await _build_positions(db, adoption_rows)
    except Exception:
        positions = ()
        logger.warning("[mca18] positions read failed", exc_info=True)

    pver = persona_version_hash(
        name=persona.name, biography=persona.biography,
        overrides=persona.overrides, is_aware_ai=bool(persona.is_aware_ai),
        updated_at=persona.updated_at)
    snapshot = SelfModelSnapshot(
        agent_id=agent_id,
        bot_user_id=effective_user_id,
        identity_binding=binding,
        persona_id=(persona.name or None),
        persona_version=pver,
        scope_chat_id=scope_chat_id,
        name=persona.name,
        aliases=(),                  # display-алиасы mca-03 — без фабрикации
        biography=persona.biography,
        style_version=style_version_hash(persona.overrides),
        traits=traits,
        interests=(),
        relations=(),
        state=mood,
        positions=positions,
        persona_enabled=persona_enabled,
        is_aware_ai=aware_state,
        bot_self_awareness=reflection,
        self_presentation_mode=(MODE_AWARE
                                if aware_state.effective(True) and
                                not aware_state.is_error
                                else MODE_IN_CHARACTER),
        # MCA-19 (ADR-1028-19 D14): «могу посмотреть изображение» — через
        # делегацию в единый vision-сервис (requested ∧ capability ok);
        # OFF/pending → False (бит-в-бит прежнего поведения).
        capabilities=build_capabilities(
            can_analyze_images=await can_analyze_images_effective(
                scope_chat_id)),
        rules_status=rules_status,
        version=_snapshot_version(
            agent_id=agent_id, persona_version=pver,
            persona_enabled=persona_enabled, is_aware_ai=aware_state,
            bot_self_awareness=reflection,
            rules_version=_rules_version(traits), scope_chat_id=scope_chat_id),
        created_at=ts,
    )
    # ── T-5088 (fallback, §28.5 `:1576`): PG недоступен → last-known-good
    # со stale-маркером (ограниченный TTL) либо минимальная тех-идентичность.
    # НИКОГДА не репортится как «успешно загруженная персона»; тихий ON
    # запрещён (честные reason-коды).
    if aware_state.is_error:
        lkg = _lkg_get(scope_chat_id)
        if lkg is not None:
            snap = dataclasses.replace(
                lkg, scope_chat_id=scope_chat_id, created_at=ts,
                stale=True, fallback="lkg")
            mca_events.emit_mca_event(
                "self_model", outcome="success", level="WARN",
                component="self_model", stage="resolve",
                reason_code="self_model_stale", chat_id=scope_chat_id,
                status="fallback_lkg")
            return snap
        snap = dataclasses.replace(
            snapshot, traits=(), state=None, positions=(),
            stale=True, fallback="minimal",
            self_presentation_mode=MODE_IN_CHARACTER)
        mca_events.emit_mca_event(
            "self_model", outcome="failed", level="WARN",
            component="self_model", stage="resolve",
            reason_code="self_model_unavailable", chat_id=scope_chat_id,
            status="fallback_minimal")
        return snap
    _lkg_put(snapshot)
    mca_events.emit_mca_event(
        "self_model", outcome="success", component="self_model",
        stage="resolve", chat_id=scope_chat_id,
        status=snapshot.self_presentation_mode)
    return snapshot


async def _latest_mood_row(db, agent_id: str, scope_chat_id: int | None,
                           now: int) -> dict | None:
    """Активное настроение (memory_kind='mood', valid_to > now) — обратимо:
    истёкшее НЕ возвращается (запрет `:1543`). chat-настроение приоритетно
    над global; None = нет активного."""
    try:
        cursor = await db.db.execute(
            "SELECT id, fact, valid_to, scope FROM graph_facts "
            "WHERE memory_kind = 'mood' AND subject_entity_id = ? AND "
            "valid_to IS NOT NULL AND valid_to > ? AND "
            "(scope = 'global' OR (scope = 'chat' AND chat_id = ?)) "
            "ORDER BY (scope = 'chat') DESC, valid_to DESC, id DESC LIMIT 1",
            (agent_id, int(now),
             int(scope_chat_id) if scope_chat_id is not None else -1))
        row = await cursor.fetchone()
    except Exception:
        logger.warning("[mca18] mood read failed", exc_info=True)
        return None
    if row is None:
        return None
    return {"id": row["id"], "fact": row["fact"], "valid_to": row["valid_to"],
            "scope": row["scope"]}


def _compile_trait_view(rule_row: dict) -> TraitView:
    """Строка `mca_behavior_rules` → TraitView с read-side гардом
    применимости (self-trait ≠ всем темам/адресатам — T-5078)."""
    applicability = _tuple_from_json(rule_row.get("applicability"))
    exclusions = _tuple_from_json(rule_row.get("exclusions"))
    reason = None
    if not applicability and not exclusions:
        # Правило без условий применимости не может действовать «всем темам»:
        # исключается из компиляции с видимой причиной (не молча).
        reason = "applicability_unbounded"
    dimension = str(rule_row.get("dimension") or "").strip()
    if not dimension:
        reason = reason or "dimension_missing"
    return TraitView(
        rule_id=int(rule_row.get("id") or 0),
        dimension=dimension,
        target_value=(float(rule_row["target_value"])
                      if rule_row.get("target_value") is not None else None),
        strength=(float(rule_row["strength"])
                  if rule_row.get("strength") is not None else None),
        scope=rule_row.get("scope"),
        applicability=applicability,
        exclusions=exclusions,
        version=int(rule_row.get("version") or 1),
        excluded_reason=reason,
    )


async def _build_positions(db, adoption_rows) -> tuple:
    """Позиции = мнения С adoption-связью (basis_refs + adopted_at).
    Мнение без adoption-связи позицией НЕ становится (D4: «в чате принято X»
    ≠ «я предпочитаю X»)."""
    out: list[Position] = []
    for link in adoption_rows or ():
        ref = str(link.get("opinion_ref") or "")
        if not ref.startswith("fact:"):
            continue
        try:
            fact = await db.get_typed_fact(int(ref.split(":", 1)[1]))
        except (TypeError, ValueError):
            fact = None
        if fact is None or fact.get("memory_kind") != "opinion":
            continue
        out.append(Position(
            opinion_ref=ref,
            text=str(fact.get("fact") or "")[:200],
            basis_refs=tuple(link.get("basis_refs") or ()),
            adopted_at=int(link.get("adopted_at") or 0),
        ))
    return tuple(out)


# ═══ T-5077: атрибуция субъекта/перспективы (D4) ════════════════════════════

@dataclass(frozen=True)
class AttributionInput:
    """Вход атрибуции: разные роли — разные ID (mca-03/22 CanonicalMessage):
    автор сообщения, автор цитаты, автор пересылки, автор исходного поста,
    изображённый автор. Роли НИКОГДА не сливаются."""

    agent_id: str
    speaker_entity_id: str | None = None       # автор сообщения (ROLE_AUTHOR)
    quote_author_entity_id: str | None = None  # ROLE_QUOTED_AUTHOR
    forward_author_entity_id: str | None = None  # ROLE_FORWARD_AUTHOR
    post_author_entity_id: str | None = None   # автор исходного поста
    depicted_author_entity_id: str | None = None  # изображённый (mca-19)
    proven_subject_entity_id: str | None = None  # доказанный субъект (ID)
    first_person_in_quote: bool = False        # «я» внутри цитаты
    bot_referent_proven: bool = False          # «бот» = доказанный референт
    self_agent_id: str | None = None           # == agent_id (совместимо)

    def role_entity_ids(self) -> dict:
        """Роли (REUSE `message_identity.ROLE_*` + изображённый автор):
        раздельный доступ — смешение ролей запрещено (D4)."""
        return {
            "author": self.speaker_entity_id,
            "quoted_author": self.quote_author_entity_id,
            "forward_author": self.forward_author_entity_id,
            "post_author": self.post_author_entity_id,
            "depicted_author": self.depicted_author_entity_id,
        }


@dataclass(frozen=True)
class Attribution:
    """Результат атрибуции (v31-колонки graph_facts)."""

    perspective: str                  # PERSPECTIVES
    subject_entity_id: str | None
    speaker_entity_id: str | None
    memory_kind: str | None
    subject_status: str               # SUBJECT_STATUSES
    ambiguous_reason: str | None = None


def attribute_memory(inp: AttributionInput,
                     declared_kind: str | None = None) -> Attribution:
    """Правила `:1533` (D4):
    * `self` — только по стабильному agent_id + исходным сообщениям;
    * «я» в цитате — относительно автора цитаты;
    * «бот» без доказанного референта — `ambiguous` (характер не меняет);
    * автор пересылки / автор поста / изображённый — разные роли."""
    agent_id = str(inp.agent_id)
    speaker = (str(inp.speaker_entity_id)
               if inp.speaker_entity_id is not None else None)
    if inp.first_person_in_quote:
        # «я» внутри цитаты → автор цитаты (это он говорит «я»), никогда не
        # наш агент, если автор цитаты не наш agent_id по доказанному ID.
        quote_author = (str(inp.quote_author_entity_id)
                        if inp.quote_author_entity_id is not None else None)
        is_self = quote_author is not None and quote_author == agent_id
        kind = _bound_kind(declared_kind, allow_self_trait=is_self)
        return Attribution(
            perspective="quoted",
            subject_entity_id=quote_author,
            speaker_entity_id=speaker,
            memory_kind=kind,
            subject_status="self" if is_self else "other",
            ambiguous_reason=None if quote_author else "quote_author_unknown")
    proven = inp.proven_subject_entity_id
    proven = str(proven) if proven is not None else None
    if proven == agent_id or speaker == agent_id:
        kind = _bound_kind(declared_kind, allow_self_trait=True)
        return Attribution(perspective="self", subject_entity_id=agent_id,
                           speaker_entity_id=speaker, memory_kind=kind,
                           subject_status="self")
    if proven is not None:
        kind = _bound_kind(declared_kind, allow_self_trait=False)
        return Attribution(perspective="other", subject_entity_id=proven,
                           speaker_entity_id=speaker, memory_kind=kind,
                           subject_status="other")
    if not inp.bot_referent_proven:
        # «бот» без доказанного референта — ambiguous: наблюдение хранится,
        # но характер/черты НЕ меняет (D4; reason `trait_attribution_
        # ambiguous`).
        kind = _bound_kind(declared_kind, allow_self_trait=False)
        if kind == "self_trait":
            kind = None               # чужая черта нашему character не пишется
        return Attribution(perspective="ambiguous", subject_entity_id=None,
                           speaker_entity_id=speaker, memory_kind=kind,
                           subject_status="ambiguous",
                           ambiguous_reason="bot_no_referent")
    kind = _bound_kind(declared_kind, allow_self_trait=False)
    return Attribution(perspective="third_party", subject_entity_id=None,
                       speaker_entity_id=speaker, memory_kind=kind,
                       subject_status="ambiguous",
                       ambiguous_reason="referent_unresolved")


def _bound_kind(declared_kind: str | None, *, allow_self_trait: bool
                ) -> str | None:
    """Вид памяти приводится к контракту; `self_trait` допустим ТОЛЬКО при
    доказанном self (иначе None — честный unknown, не выдумка)."""
    if declared_kind is None:
        return None
    kind = str(declared_kind).strip()
    if kind not in MEMORY_KINDS:
        return None
    if kind == "self_trait" and not allow_self_trait:
        return None
    return kind


def subject_status_from_attribution(attr: Attribution) -> str:
    return attr.subject_status


# ═══ T-5078: запреты таблицы `:1535–1544` — guard-функции ═══════════════════

@dataclass(frozen=True)
class GuardVerdict:
    """Результат запрета: allowed/reason — видимые причины (не молчаливые)."""

    allowed: bool
    reason: str


def guard_fact_not_self_trait(source_kind: str | None,
                              target_kind: str | None) -> GuardVerdict:
    """Факт о мире/участнике ≠ черта себя (`:1537`)."""
    if source_kind == "world_fact" and target_kind == "self_trait":
        return GuardVerdict(False, "fact_is_not_self_trait")
    return GuardVerdict(True, "ok")


def guard_own_output_not_proof(evidence_kinds, target_kind: str
                               ) -> GuardVerdict:
    """Собственный прошлый ответ ≠ доказательство истинности (`:1538`):
    self_event в основаниях факта о мире не повышает уверенность."""
    kinds = {str(k) for k in (evidence_kinds or ())}
    if "self_event" in kinds and target_kind == "world_fact":
        return GuardVerdict(False, "own_output_is_not_proof")
    return GuardVerdict(True, "ok")


def guard_trait_applicability(applicability, exclusions) -> GuardVerdict:
    """Self-trait ≠ всем темам/адресатам (`:1539`): нужны условия
    применимости или исключения."""
    if not tuple(applicability or ()) and not tuple(exclusions or ()):
        return GuardVerdict(False, "trait_applicability_unbounded")
    return GuardVerdict(True, "ok")


def guard_opinion_not_fact(memory_kind: str | None,
                           target_use: str) -> GuardVerdict:
    """Мнение ≠ объективный факт (`:1540`): мнение не может компилироваться
    в factual constraint; только как помеченная позиция/голос."""
    if memory_kind == "opinion" and target_use == "factual_constraint":
        return GuardVerdict(False, "opinion_is_not_fact")
    return GuardVerdict(True, "ok")


def guard_belief_not_value(memory_kind: str | None, *,
                           has_adoption_link: bool) -> GuardVerdict:
    """Убеждение сна о мире ≠ личная ценность (`:1541`): позиция — только
    через adoption-связь."""
    if memory_kind == "belief" and not has_adoption_link:
        return GuardVerdict(False, "belief_is_not_personal_value")
    return GuardVerdict(True, "ok")


def guard_paradigm_period(memory_kind: str | None, valid_from: int | None,
                          valid_to: int | None, now: int | None = None
                          ) -> GuardVerdict:
    """Парадигма действует только в своём периоде/области (`:1542`):
    вне valid_from/valid_to — неприменима (не «старая закономерность
    навсегда»)."""
    if memory_kind != "paradigm":
        return GuardVerdict(True, "ok")
    ts = int(now if now is not None else time.time())
    if valid_from is not None and ts < int(valid_from):
        return GuardVerdict(False, "paradigm_before_period")
    if valid_to is not None and ts >= int(valid_to):
        return GuardVerdict(False, "paradigm_after_period")
    if valid_from is None and valid_to is None:
        return GuardVerdict(False, "paradigm_period_unbounded")
    return GuardVerdict(True, "ok")


def guard_mood_reversible(memory_kind: str | None, valid_to: int | None,
                          now: int | None = None) -> GuardVerdict:
    """Настроение — кратковременная поправка с временем окончания (`:1543`):
    без valid_to запись отклоняется (TTL обязателен); истёкшее — неактивно.
    Настроение никогда не пишет self_trait/identity (доп. проверка в
    `check_typed_write`)."""
    if memory_kind != "mood":
        return GuardVerdict(True, "ok")
    if valid_to is None:
        return GuardVerdict(False, "mood_ttl_required")
    ts = int(now if now is not None else time.time())
    if ts >= int(valid_to):
        return GuardVerdict(False, "mood_expired")
    return GuardVerdict(True, "ok")


def guard_lesson_not_identity(source_kind: str | None,
                              target_kind: str | None) -> GuardVerdict:
    """Проверенный урок mca-16 ≠ идентичность (`:1544`): lesson не
    конвертируется в self_trait (граница mca-16, CA-18-2)."""
    if source_kind == "lesson" and target_kind == "self_trait":
        return GuardVerdict(False, "lesson_is_not_identity")
    return GuardVerdict(True, "ok")


def check_typed_write(*, memory_kind: str | None, perspective: str | None,
                      subject_entity_id: str | None, agent_id: str,
                      applicability=(), exclusions=(), valid_from: int | None
                      = None, valid_to: int | None = None,
                      now: int | None = None) -> GuardVerdict:
    """Сводный write-гард таблицы запретов (вызывается до `save_typed_fact`).
    Порядок: субъект self → вид-специфичные запреты."""
    if memory_kind == "self_trait":
        if perspective != "self" or subject_entity_id != agent_id:
            return GuardVerdict(False, "self_trait_requires_proven_self")
        return guard_trait_applicability(applicability, exclusions)
    if memory_kind == "mood":
        verdict = guard_mood_reversible(memory_kind, valid_to, now)
        if not verdict.allowed:
            return verdict
        if subject_entity_id is not None and subject_entity_id != agent_id:
            return GuardVerdict(False, "mood_subject_mismatch")
        return verdict
    if memory_kind == "paradigm":
        return guard_paradigm_period(memory_kind, valid_from, valid_to, now)
    if memory_kind == "lesson":
        # lesson хранится в mca_experience (mca-16); в graph_facts — только
        # read-side ссылка, self_trait из него не создаётся (CA-18-2).
        return GuardVerdict(True, "ok_reference_only")
    return GuardVerdict(True, "ok")


async def store_typed_memory(db, *, chat_id: int, fact: str,
                             attribution: Attribution, agent_id: str,
                             memory_kind: str | None,
                             scope: str | None = None,
                             valid_from: int | None = None,
                             valid_to: int | None = None,
                             confidence_basis: str | None = None,
                             applicability=(), exclusions=(),
                             evidence_kinds=(), now: int | None = None
                             ) -> tuple[int | None, GuardVerdict]:
    """Запись типированной памяти с enforcement запретов (D4): сначала
    guard'ы, затем `save_typed_fact`. Возвращает (id, verdict); отказ —
    (None, verdict с причиной) — не молчаливый."""
    verdict = check_typed_write(
        memory_kind=memory_kind, perspective=attribution.perspective,
        subject_entity_id=attribution.subject_entity_id, agent_id=agent_id,
        applicability=applicability, exclusions=exclusions,
        valid_from=valid_from, valid_to=valid_to, now=now)
    if not verdict.allowed:
        return None, verdict
    verdict = guard_own_output_not_proof(evidence_kinds,
                                         memory_kind or "world_fact")
    if not verdict.allowed:
        return None, verdict
    if attribution.perspective == "ambiguous":
        mca_events.emit_mca_event(
            "self_model.attribution", outcome="skipped",
            component="self_model",
            reason_code="trait_attribution_ambiguous",
            chat_id=chat_id, status=attribution.ambiguous_reason or "unknown")
    fact_id = await db.save_typed_fact(
        chat_id=chat_id, fact=fact,
        subject_entity_id=attribution.subject_entity_id,
        speaker_entity_id=attribution.speaker_entity_id,
        perspective=attribution.perspective,
        memory_kind=memory_kind, scope=scope, valid_from=valid_from,
        valid_to=valid_to, confidence_basis=confidence_basis)
    return fact_id, GuardVerdict(True, "ok")


# ═══ T-5088: last-known-good snapshot (process-local, bounded) ══════════════

_LKG: dict[str, tuple[SelfModelSnapshot, float]] = {}
_LKG_MAX = 64


def _lkg_key(scope_chat_id: int | None) -> str:
    return f"scope:{scope_chat_id if scope_chat_id is not None else 'g'}"


def _lkg_put(snapshot: SelfModelSnapshot) -> None:
    try:
        if snapshot.stale:
            return
        if len(_LKG) >= _LKG_MAX:
            _LKG.pop(next(iter(_LKG)))
        _LKG[_lkg_key(snapshot.scope_chat_id)] = (snapshot, time.time())
    except Exception:      # pragma: no cover - fail-open кеш
        pass


def _lkg_get(scope_chat_id: int | None) -> SelfModelSnapshot | None:
    """Свежий LKG (TTL env `MCA_SELF_MODEL_FALLBACK_TTL_SECONDS`).

    TTL обязан быть ограниченным (§28.5 `:1576`): ttl≤0 → LKG не выдаётся
    (честный minimal-fallback вместо «вечно живого» снимка)."""
    try:
        entry = _LKG.get(_lkg_key(scope_chat_id))
        if entry is None:
            return None
        snap, ts = entry
        ttl = mca_gates.self_model_fallback_ttl_seconds()
        if ttl <= 0:
            return None
        if (time.time() - ts) > ttl:
            return None
        return snap
    except Exception:      # pragma: no cover
        return None


def lkg_invalidate() -> None:
    """Сброс LKG (тесты/владелец)."""
    _LKG.clear()


# ═══ T-5081: holder кадра запуска (один snapshot на ответ, I-1) ═════════════

_RUN_FRAME: ContextVar["object | None"] = ContextVar("mca18_run_frame",
                                                      default=None)


@dataclass(frozen=True)
class RunFrame:
    """Кадр текущего запуска ответа: один snapshot → один frame → одна
    версия во ВСЕХ путях этого запуска (решение/direct/verbalizer/...)."""

    frame: "BehaviorFrame"
    chat_id: int | None
    applied_tag: str          # маркировка для mca-22 ledger (R17-safe)


def set_run_frame(frame: "BehaviorFrame", chat_id: int | None) -> RunFrame:
    tag = ""
    if frame.applied_rules:
        tag = "trait:" + ";trait:".join(
            f"{r.rule_id}:v{r.version}" for r in frame.applied_rules)[:200]
    rf = RunFrame(frame=frame, chat_id=chat_id, applied_tag=tag)
    _RUN_FRAME.set(rf)
    return rf


def current_run_frame() -> "BehaviorFrame | None":
    rf = _RUN_FRAME.get()
    return rf.frame if rf is not None else None


def current_run_frame_version() -> str | None:
    rf = _RUN_FRAME.get()
    return rf.frame.version if rf is not None else None


def current_run_frame_tag() -> str:
    rf = _RUN_FRAME.get()
    return rf.applied_tag if rf is not None else ""


# ═══ T-5079: lifecycle TraitObservation → BehaviorRule (D5) ═════════════════

# 8 начальных dimensions (§28.4 `:1554`; закрытый набор; новое имя от LLM →
# candidate с причиной, исполняемый код не создаётся).
INITIAL_DIMENSIONS: tuple[str, ...] = (
    "прямота", "резкость", "сарказм", "краткость", "инициативность",
    "любопытство", "склонность спорить", "теплота")

# Детерминированные инструкции компиляции (2-е лицо; §28.4 `:1556` — компакт,
# без заготовок реплик; обязанность сохранить смысл/задачу — в каждой).
DIMENSION_INSTRUCTIONS: dict[str, str] = {
    "прямота":
        "Ты отвечаешь прямо и по существу, без обходных формулировок; "
        "не теряй смысл просьбы.",
    "резкость":
        "Ты отвечаешь резче обычного в уместном споре или поддразнивании; "
        "без оскорблений и без потери смысла просьбы.",
    "сарказм":
        "Ты можешь использовать мягкий сарказм в дружеской перепалке; "
        "задача и адресат не страдают.",
    "краткость":
        "Ты отвечаешь короче обычного, только суть; задача выполняется "
        "полностью.",
    "инициативность":
        "Ты предлагаешь следующий шаг или уточнение, когда это уместно; "
        "без навязчивости.",
    "любопытство":
        "Ты задашь один уместный уточняющий вопрос, если тема это "
        "позволяет; ответ не подменяется вопросом.",
    "склонность спорить":
        "Ты готов возразить и привести аргумент в споре; без перехода "
        "на личности и без срыва задачи.",
    "теплота":
        "Ты отвечаешь теплее и поддерживающе; фактология и задача не "
        "искажаются.",
}

# Конфликт с ядром владельца (детерминированные маркеры «owner_core против
# dimension»; инженерный дефолт, владелец правит ядром). Маркер в
# `personas.system_prompt_overrides` → правило отклоняется (trait_conflict_core).
CORE_CONFLICT_MARKERS: dict[str, tuple[str, ...]] = {
    "прямота": ("не будь прямолинейным", "помягче"),
    "резкость": ("без резкости", "не груби"),
    "сарказм": ("без сарказма", "без иронии"),
    "краткость": ("отвечай развёрнуто", "не будь кратким"),
    "инициативность": ("не предлагай сам", "без инициативы"),
    "любопытство": ("не задавай вопросов", "без вопросов"),
    "склонность спорить": ("не спорь", "без споров", "соглашайся"),
    "теплота": ("суше", "без тепла", "нейтральнее"),
}

# Измерения, принадлежащие ДРУГИМ механизмам — правилом НЕ становятся
# (границы CA-18-2/3; quality_regression → mca-16 наблюдение).
FOREIGN_DIMENSIONS: frozenset[str] = frozenset({
    "quality_regression", "полезность", "utility", "quality"})

# MCA-18 (rework H-2): детерминированный маппинг legacy-текста черты в
# закрытый набор dimensions (инженерный стем-матч, НЕ NLP-классификатор и не
# второй LLM). Порядок = приоритет при пересечении маркеров.
DIMENSION_TEXT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("сарказм", ("сарказ", "ирон", "язвит", "ехидн")),
    ("резкость", ("резк", "резче", "груб", "жёстк", "жестк")),
    ("склонность спорить", ("спор", "возража", "перечит",
                            "не соглашается")),
    ("краткость", ("кратк", "коротк", "сжато", "только суть", "без воды")),
    ("инициативность", ("инициатив", "сам предлага", "предлагает сам",
                        "берёт на себ", "берет на себ")),
    ("любопытство", ("любопыт", "интересуется", "задаёт вопрос",
                     "задает вопрос", "расспрашива")),
    ("прямота", ("прям", "по существу", "без обход")),
    ("теплота", ("тепл", "тёпл", "поддерж", "забот", "мягче")),
)


def infer_dimension(text: str) -> str | None:
    """Маппинг свободного текста черты в dimension из закрытого набора
    (§28.4 `:1554`). Нет совпадения → None (неприведённый кандидат с
    причиной `candidate_unmapped_dimension`; исполняемое правило не
    создаётся)."""
    low = str(text or "").casefold()
    for dimension, markers in DIMENSION_TEXT_MARKERS:
        if any(marker in low for marker in markers):
            return dimension
    return None

_OBS_MAX_TEXT = 500          # R17: normalized кап; raw — дословный артефакт


def _norm_observation_text(text: str) -> str:
    return " ".join(str(text or "").split())[:_OBS_MAX_TEXT]


def event_refs_hash(refs) -> str:
    """Дедуп по ИСХОДНЫМ событиям (не по формулировке summary, §28.4)."""
    material = "\x1f".join(sorted(str(r) for r in (refs or ())))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


async def find_rule_id(db, *, agent_id: str,
                       dimension: str | None) -> int | None:
    """ID существующего правила субъекта по dimension (для bounded-
    подкрепления при ПОВТОРНОМ независимом наблюдении; None — правила нет,
    первое наблюдение подкреплением не считается)."""
    if not dimension:
        return None
    try:
        cursor = await db.db.execute(
            "SELECT id FROM mca_behavior_rules WHERE agent_id = ? AND "
            "dimension = ? LIMIT 1", (str(agent_id), str(dimension)))
        row = await cursor.fetchone()
        return int(row["id"]) if row is not None else None
    except Exception:
        return None


async def record_trait_observation(
        db, *, agent_id: str, text: str, source_refs=(), subject_status: str
        = "ambiguous", chat_id: int | None = None, dimension: str | None
        = None, observed_at: int | None = None, legacy_ref: int | None
        = None) -> int | None:
    """Записать наблюдение черты (дословный raw + нормализат + источники).
    Дедуп по исходным событиям: тот же набор refs → no-op (возвращает
    существующий id). Транзакция — `write_transaction` (mca-01)."""
    if not mca_gates.trait_rules_enabled():
        return None
    raw = _norm_observation_text(text)
    if not raw:
        return None
    refs = tuple(str(r) for r in (source_refs or ()) if str(r).strip())
    if subject_status not in SUBJECT_STATUSES:
        subject_status = "ambiguous"
    if dimension is not None and str(dimension).strip() \
            and str(dimension).strip() not in INITIAL_DIMENSIONS \
            and str(dimension).strip() not in FOREIGN_DIMENSIONS:
        dimension = None                     # неприведённое = NULL
    ts = int(observed_at if observed_at is not None else time.time())
    refs_hash = event_refs_hash(refs)

    async def _body(conn):
        if refs:
            # Дедуп по событиям: observation с тем же набором источников.
            cursor = await conn.execute(
                "SELECT id FROM mca_trait_observations WHERE agent_id = ? "
                "AND raw_text = ? AND source_refs = ? LIMIT 1",
                (agent_id, raw, json.dumps(refs, ensure_ascii=False)))
            row = await cursor.fetchone()
            if row is not None:
                return int(row["id"])
        cursor = await conn.execute(
            "INSERT INTO mca_trait_observations (agent_id, chat_id, "
            "dimension, raw_text, normalized, source_refs, subject_status, "
            "observed_at, source_chat_id, legacy_ref, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (agent_id, chat_id, dimension, raw, raw[:200],
             json.dumps(refs, ensure_ascii=False) if refs else None,
             subject_status, ts, chat_id, legacy_ref, ts))
        return int(cursor.lastrowid)

    return await db.write_transaction(_body,
                                      op_name="trait_observation")


async def _owner_core_conflict(db, scope_chat_id: int | None,
                               dimension: str) -> str | None:
    """Конфликт с ядром владельца: маркер в effective `overrides`
    (owner_core — высший слой precedence, `bot_persona.py:44–46`)."""
    from services import bot_persona
    persona = await bot_persona.resolve_bot_persona(scope_chat_id)
    core = " ".join(str(persona.overrides or "").lower().split())
    if not core:
        return None
    for marker in CORE_CONFLICT_MARKERS.get(dimension, ()):
        if marker in core:
            return f"owner_core:{marker}"
    return None


async def promote_observation(
        db, observation_id: int, *, scope_chat_id: int | None = None
) -> tuple[int | None, GuardVerdict]:
    """Авто-валидация наблюдения → BehaviorRule (стадии observed→candidate→
    active; ручное одобрение не требуется, `:1552`). Честные отказы с
    причиной; quality_regression → НЕ правило (mca-16-наблюдение)."""
    if not mca_gates.trait_rules_enabled():
        return None, GuardVerdict(False, "trait_rules_disabled")
    try:
        cursor = await db.db.execute(
            "SELECT * FROM mca_trait_observations WHERE id = ?",
            (int(observation_id),))
        obs = await cursor.fetchone()
    except Exception:
        obs = None
    if obs is None:
        return None, GuardVerdict(False, "observation_missing")
    dimension = obs["dimension"]
    subject_status = obs["subject_status"]
    # 1) границы механизмов: quality_regression → mca-16, не правило.
    if dimension is not None and str(dimension) in FOREIGN_DIMENSIONS:
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="candidate_compile",
            reason_code="trait_rule_rejected",
            status="foreign_dimension")
        return None, GuardVerdict(False, "foreign_dimension_routes_to_"
                                         "experience")
    # 2) субъект=self доказан.
    if subject_status != "self":
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="validation", reason_code="trait_rule_rejected",
            status="subject_not_self")
        return None, GuardVerdict(False, "subject_not_self")
    # 3) источник существует (mca-04a refs; ручная/legacy — ref-указатель).
    try:
        refs = tuple(json.loads(obs["source_refs"] or "[]"))
    except (TypeError, ValueError):
        refs = ()
    if not refs and obs["legacy_ref"] is None:
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="validation", reason_code="trait_rule_rejected",
            status="source_missing")
        return None, GuardVerdict(False, "source_missing")
    # 4) dimension приведён? Новое имя от LLM уже спулено в NULL на записи;
    #    NULL-observation → остаётся НЕприведённым кандидатом с причиной
    #    (`:1554`) — исполняемое правило НЕ создаётся (rules.dimension NOT
    #    NULL по санкции §8.1: правило существует только для приведённого
    #    dimension).
    if not dimension:
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="candidate_compile", reason_code="trait_rule_rejected",
            status="candidate_unmapped_dimension")
        return None, GuardVerdict(True, "candidate_unmapped_dimension")
    # 5) конфликт с ядром владельца.
    conflict = await _owner_core_conflict(db, scope_chat_id, dimension)
    if conflict:
        rule_id = await _upsert_rule_candidate(db, obs, obs["source_chat_id"],
                                               f"rejected:{conflict}",
                                               status="rejected")
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="validation", reason_code="trait_conflict_core",
            chat_id=scope_chat_id, status=conflict[:120])
        return rule_id, GuardVerdict(False, f"conflict_core:{conflict}")
    # 6) активация (subject/источник/ядро — ок): chat-правило получает
    # детерминированную chat-bound applicability (запрет «всем темам/
    # адресатам», `:1539`); global БЕЗ условий остаётся кандидатом до
    # явного ограничения владельцем (chat→global — явное правило, `:1584`).
    chat_id = obs["source_chat_id"]
    if chat_id is not None:
        rule_id = await _upsert_rule_candidate(
            db, obs, chat_id, None, status="active",
            applicability=(f"chat:{int(chat_id)}",))
        mca_events.emit_mca_event(
            "self_model", outcome="success", component="self_model",
            stage="activation", chat_id=scope_chat_id,
            entity_ids=[f"rule:{rule_id}"])
        return rule_id, GuardVerdict(True, "ok")
    rule_id = await _upsert_rule_candidate(
        db, obs, None, "global_needs_applicability", status="candidate")
    mca_events.emit_mca_event(
        "self_model", outcome="skipped", component="self_model",
        stage="activation", reason_code="trait_rule_rejected",
        chat_id=scope_chat_id, status="global_needs_applicability")
    return rule_id, GuardVerdict(True, "candidate_global_needs_applicability")


async def _upsert_rule_candidate(
        db, obs, chat_id: int | None, reason: str | None, *,
        status: str = "candidate", applicability=()) -> int | None:
    """Один dimension = одно правило субъекта: candidate/active/rejected
    (UNIQUE-семантика по (agent_id, dimension) — естественный ключ;
    повторное наблюдение ДОБАВЛЯЕТСЯ в source_observation_ids, версию не
    двигает — подкрепление тем же эпизодом запрещено)."""
    agent_id = obs["agent_id"]
    dimension = obs["dimension"]
    now = int(time.time())
    applicability_json = (json.dumps(list(applicability),
                                     ensure_ascii=False)
                          if applicability else None)

    async def _body(conn):
        cursor = await conn.execute(
            "SELECT id, source_observation_ids, version, target_value, "
            "strength, applicability FROM mca_behavior_rules WHERE "
            "agent_id = ? AND dimension = ? LIMIT 1", (agent_id, dimension))
        row = await cursor.fetchone()
        if row is not None:
            # L-3 (rework): контракт «наблюдение ДОБАВЛЯЕТСЯ в
            # source_observation_ids» теперь исполнен (lineage без
            # подкрепления: version/strength не двигаются).
            try:
                ids = [int(x) for x in json.loads(
                    row["source_observation_ids"] or "[]")]
            except (TypeError, ValueError):
                ids = []
            obs_id = int(obs["id"])
            if obs_id not in ids:
                ids.append(obs_id)
            await conn.execute(
                "UPDATE mca_behavior_rules SET status = ?, "
                "status_reason = COALESCE(?, status_reason), "
                "applicability = COALESCE(applicability, ?), "
                "source_observation_ids = ?, updated_at = ? "
                "WHERE id = ?",
                (status, reason, applicability_json,
                 json.dumps(ids, ensure_ascii=False), now, row["id"]))
            return int(row["id"])
        cursor = await conn.execute(
            "INSERT INTO mca_behavior_rules (agent_id, dimension, "
            "target_value, strength, confidence_basis, scope, "
            "applicability, exclusions, status, status_reason, "
            "source_observation_ids, version, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (agent_id, dimension, None, None, None,
             "chat" if chat_id is not None else None,
             applicability_json, None,
             status, reason,
             json.dumps([int(obs["id"])], ensure_ascii=False), now))
        return int(cursor.lastrowid)

    try:
        return await db.write_transaction(_body, op_name="rule_upsert")
    except Exception:
        logger.warning("[mca18] rule upsert failed", exc_info=True)
        return None


async def supersede_rule(db, rule_id: int, *, reason: str,
                         scope_chat_id: int | None = None) -> bool:
    """supersede: противоположное наблюдение/локализация — не склейка."""
    return await _rule_transition(db, rule_id, "superseded", reason,
                                  scope_chat_id)


async def suspend_rule(db, rule_id: int, *, reason: str,
                       scope_chat_id: int | None = None) -> bool:
    return await _rule_transition(db, rule_id, "suspended", reason,
                                  scope_chat_id)


async def reactivate_rule(db, rule_id: int, *, reason: str,
                          scope_chat_id: int | None = None) -> bool:
    """Возобновление приостановленного (владелец/новые данные)."""
    return await _rule_transition(db, rule_id, "active", reason,
                                  scope_chat_id)


async def _rule_transition(db, rule_id: int, status: str, reason: str,
                           scope_chat_id: int | None) -> bool:
    if status not in RULE_STATUSES:
        return False
    now = int(time.time())

    async def _body(conn):
        cursor = await conn.execute(
            "SELECT status FROM mca_behavior_rules WHERE id = ?",
            (int(rule_id),))
        row = await cursor.fetchone()
        if row is None:
            return False
        if row["status"] in ("rejected", "superseded") \
                and status not in ("rejected", "superseded"):
            return False               # терминальное НЕ реактивируется
        await conn.execute(
            "UPDATE mca_behavior_rules SET status = ?, status_reason = ?, "
            "updated_at = ? WHERE id = ?",
            (status, str(reason)[:200], now, int(rule_id)))
        return True

    try:
        ok = await db.write_transaction(_body, op_name="rule_transition")
    except Exception:
        logger.warning("[mca18] rule transition failed", exc_info=True)
        return False
    if ok:
        mca_events.emit_mca_event(
            "self_model", outcome="success", component="self_model",
            stage="activation", chat_id=scope_chat_id,
            entity_ids=[f"rule:{int(rule_id)}"], status=status)
    return ok


def rule_tag(rule_id: int, version: int) -> str:
    """Маркер «ответ создан под чертой» (mca-22 ledger source_feature)."""
    return f"trait:{int(rule_id)}:v{int(version)}"


async def _rule_sources_independent(db, rule_id: int, refs) -> bool:
    """Анти-самоусиление (A61): источник независим, если это НЕ ответ бота,
    порождённый ПОД ЭТОЙ чертой. fact-ref → graph_facts origin=bot_self_reply
    (суть собственных ответов) — проверяем ledger-маркер правила; legacy-
    refs/пользовательские события — независимы."""
    for ref in (refs or ()):
        ref = str(ref)
        if not ref.startswith("fact:"):
            return True                # не self-ответ — независимый
        try:
            fid = int(ref.split(":", 1)[1])
        except (TypeError, ValueError):
            return True
        try:
            cursor = await db.db.execute(
                "SELECT origin, tg_message_id, chat_id FROM graph_facts "
                "WHERE id = ?", (fid,))
            fact = await cursor.fetchone()
        except Exception:
            return True
        if fact is None or fact["origin"] != "bot_self_reply":
            return True
        # Ответ бота под чертой? ledger.source_feature содержит тег правила.
        if fact["tg_message_id"] is not None:
            try:
                cursor = await db.db.execute(
                    "SELECT source_feature FROM mca_bot_outputs WHERE "
                    "chat_id = ? AND tg_message_id = ? ORDER BY revision_no "
                    "DESC LIMIT 1",
                    (fact["chat_id"], int(fact["tg_message_id"])))
                row = await cursor.fetchone()
            except Exception:
                row = None
            if row is not None and f"trait:{int(rule_id)}:" in \
                    str(row["source_feature"] or ""):
                continue               # свой ответ под ЭТОЙ чертой
        return True
    return False                       # все источники — ответы под чертой


async def reinforce_rule(db, rule_id: int, *, delta: float, refs=(),
                         cycle_events=(), now: int | None = None,
                         scope_chat_id: int | None = None) -> GuardVerdict:
    """Ограниченное обновление dimension (A61/§28.4 `:1562`):
    * дедуп по исходным событиям (тот же эпизод → no-op);
    * собственные ответы под чертой — НЕ независимое подтверждение;
    * шаг ≤0.1/цикл, ≤0.2/24 ч (env-only); ослабление (delta<0) — всегда
      допустимо; реверс/отмена — через supersede/suspend."""
    if not mca_gates.trait_rules_enabled():
        return GuardVerdict(False, "trait_rules_disabled")
    ts = int(now if now is not None else time.time())
    try:
        cursor = await db.db.execute(
            "SELECT id, target_value, strength, version, "
            "event_dedup_hash, status FROM mca_behavior_rules WHERE id = ?",
            (int(rule_id),))
        rule = await cursor.fetchone()
    except Exception:
        rule = None
    if rule is None or rule["status"] != "active":
        return GuardVerdict(False, "rule_not_active")
    ref_list = tuple(str(r) for r in (refs or ()) if str(r).strip())
    ev_hash = event_refs_hash(ref_list)
    if rule["event_dedup_hash"] and ev_hash == str(rule["event_dedup_hash"]):
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="validation", reason_code="trait_reinforcement_dedup",
            chat_id=scope_chat_id, entity_ids=[f"rule:{int(rule_id)}"])
        return GuardVerdict(False, "reinforcement_dedup")
    if not await _rule_sources_independent(db, rule_id, ref_list):
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="validation", reason_code="trait_reinforcement_dedup",
            chat_id=scope_chat_id, entity_ids=[f"rule:{int(rule_id)}"],
            status="own_output_under_trait")
        return GuardVerdict(False, "own_output_not_independent")
    # Ослабление — без капа (ослабление/отмена допускаются, `:1562`).
    delta = float(delta)
    if delta > 0:
        cap = min(mca_gates.trait_max_step_per_cycle(),
                  mca_gates.trait_max_step_24h())
        if delta > cap + 1e-9:
            mca_events.emit_mca_event(
                "self_model", outcome="skipped", component="self_model",
                stage="validation", reason_code="trait_step_limit",
                chat_id=scope_chat_id,
                entity_ids=[f"rule:{int(rule_id)}"])
            return GuardVerdict(False, "trait_step_limit")
    base = float(rule["target_value"] if rule["target_value"] is not None
                 else 0.0)
    new_value = max(0.0, min(1.0, base + delta))
    new_version = int(rule["version"] or 1) + (1 if delta > 0 else 0)

    async def _body(conn):
        await conn.execute(
            "UPDATE mca_behavior_rules SET target_value = ?, version = ?, "
            "event_dedup_hash = ?, updated_at = ? WHERE id = ?",
            (new_value, new_version, ev_hash, ts, int(rule_id)))
        return True

    try:
        await db.write_transaction(_body, op_name="rule_reinforce")
    except Exception:
        logger.warning("[mca18] rule reinforce failed", exc_info=True)
        return GuardVerdict(False, "write_failed")
    return GuardVerdict(True, "ok")


# ═══ T-5080: select_behavior → BehaviorFrame (D6) ═══════════════════════════

@dataclass(frozen=True)
class CompiledRule:
    """Применимое правило кадра: ID+версия (trace/marking) + детерминированная
    инструкция во 2-м лице (≠ цитаты/справки — GEN-R18)."""

    rule_id: int
    dimension: str
    version: int
    target_value: float | None
    instruction: str
    source: str                        # derived_traits | scoped_request


@dataclass(frozen=True)
class RejectedRule:
    rule_id: int
    dimension: str
    reason: str


@dataclass(frozen=True)
class BehaviorFrame:
    """Кадр поведения (frozen; сериализация структурированных данных,
    НЕ «бот»→«я» replace): snapshot_version, адресат, self-идентичность,
    режим, применимые правила с ID, позиции, эмоц. поправка, factual
    constraints, rejected_rules с причинами."""

    snapshot_version: str
    scope_chat_id: int | None
    addressee: str | None
    agent_id: str
    bot_user_id: int | None
    self_presentation_mode: str
    is_aware_ai: bool                 # effective из snapshot (кадр самодостаточен)
    applied_rules: tuple[CompiledRule, ...]
    positions: tuple[Position, ...]
    mood: MoodState | None
    factual_constraints: tuple[str, ...]
    scoped_request: tuple[str, ...]
    rejected_rules: tuple[RejectedRule, ...]
    stale: bool = False
    fallback: str = ""
    created_at: int = 0

    @property
    def version(self) -> str:
        """Версия кадра = snapshot_version (+ stale-флаг) — в trace/Decision
        (CA-18-7 аддитивно; enum mca-09 не меняется)."""
        return self.snapshot_version + (":stale" if self.stale else "")


def _dimension_in_text(dimension: str, text: str) -> bool:
    """Детерминированный стем-матч dimension в тексте просьбы (RU
    морфология: «без резкости»/«резким» — не подстрока номинатива).
    Стем = первые max(4, len-2) символа слова; достаточно для закрытого
    набора из 8 dimensions; это НЕ NLP-классификатор."""
    text = str(text or "").lower()
    for word in str(dimension or "").lower().split():
        stem = word[:max(4, len(word) - 2)]
        if stem and stem in text:
            return True
    return False


def _scope_mismatch_reason(applicability, scope_chat_id: int | None
                           ) -> str | None:
    """S-1 (rework, Scanner T-5093): read-side enforcement chat-биндинга
    (spec §6/D8; §28.4 `:1584` — особенности одного чата локальны;
    chat→global — явное правило владельца). Токены `chat:<id>` в
    applicability (создаёт `promote_observation`) действуют ТОЛЬКО при
    запуске в чате `<id>`; чужой чат или глобальный запуск →
    `out_of_scope_chat` (fail-closed: нечитаемый биндинг не применяется).
    Правила без chat-биндинга (global, темы/адресаты) — без изменений."""
    bindings: set[int] = set()
    for token in applicability or ():
        text = str(token).strip()
        if not text.startswith("chat:"):
            continue
        try:
            bindings.add(int(text[len("chat:"):]))
        except ValueError:
            return "out_of_scope_chat"
    if not bindings:
        return None
    if scope_chat_id is None:
        return "out_of_scope_chat"
    try:
        return (None if int(scope_chat_id) in bindings
                else "out_of_scope_chat")
    except (TypeError, ValueError):
        return "out_of_scope_chat"


def select_behavior(snapshot: SelfModelSnapshot, bundle=None, *,
                    scoped_request=(), addressee: str | None = None,
                    now: int | None = None) -> BehaviorFrame:
    """Детерминированный компилятор (без LLM-пересказа, `:1568`).

    Порядок конфликтов ДО генерации = `CHARACTER_PRECEDENCE` (mca-08, не
    менять): owner_core/owner_style (статика персоны — вне frame, рендер
    точки сборки) → scoped_request (разовая просьба — действует на ответ,
    НЕ удаляет черту) → derived_traits (активные правила) → state (mood,
    TTL). K2 OFF/stale → пустые derived_traits с честной причиной. S-1:
    chat-bound applicability (`chat:<id>`) сверяется с чатом запуска —
    чужое chat-правило исключено с причиной `out_of_scope_chat`."""
    ts = int(now if now is not None else time.time())
    applied: list[CompiledRule] = []
    rejected: list[RejectedRule] = []
    scoped = tuple(str(s) for s in (scoped_request or ()) if str(s).strip())
    if snapshot.rules_status == "on" and not snapshot.stale:
        scoped_lower = " ".join(scoped).lower()
        for trait in snapshot.traits:
            if not trait.included:
                rejected.append(RejectedRule(
                    rule_id=trait.rule_id, dimension=trait.dimension,
                    reason=trait.excluded_reason or "excluded"))
                continue
            # S-1 (rework): chat-биндинг правила ≠ чат запуска → правило
            # исключено с честной причиной (не молча; глобальные запуски и
            # правила без chat-биндинга не задеты).
            scope_reason = _scope_mismatch_reason(
                trait.applicability, snapshot.scope_chat_id)
            if scope_reason:
                rejected.append(RejectedRule(
                    rule_id=trait.rule_id, dimension=trait.dimension,
                    reason=scope_reason))
                continue
            if trait.dimension in FOREIGN_DIMENSIONS:
                rejected.append(RejectedRule(
                    rule_id=trait.rule_id, dimension=trait.dimension,
                    reason="foreign_dimension"))
                continue
            instruction = DIMENSION_INSTRUCTIONS.get(trait.dimension)
            if not instruction:
                rejected.append(RejectedRule(
                    rule_id=trait.rule_id, dimension=trait.dimension,
                    reason="unmapped_dimension"))
                continue
            # Разовая просьба («без шуток») перекрывает dimension НА ЭТОТ
            # ответ — черта остаётся (mca-08 scoped_request precedence).
            # Матч — по детерминированному стему слова (морфология RU:
            # «без резкости» ≠ подстрока «резкость»).
            if scoped_lower and _dimension_in_text(trait.dimension,
                                                   scoped_lower):
                rejected.append(RejectedRule(
                    rule_id=trait.rule_id, dimension=trait.dimension,
                    reason="shadowed_by_scoped_request"))
                continue
            applied.append(CompiledRule(
                rule_id=trait.rule_id, dimension=trait.dimension,
                version=trait.version, target_value=trait.target_value,
                instruction=instruction, source="derived_traits"))
    elif snapshot.rules_status != "on":
        rejected.append(RejectedRule(rule_id=0, dimension="",
                                     reason=f"rules_{snapshot.rules_status}"))
    # factual constraints — ТОЛЬКО факты (мнение ≠ факт, запрет `:1540`);
    # bundle.constraints — уже проверенный слой mca-07.
    constraints = tuple(str(c) for c in (getattr(bundle, "constraints", ())
                                         or ()) if str(c).strip())
    positions = snapshot.positions if not snapshot.stale else ()
    mca_events.emit_mca_event(
        "self_model", outcome="success", component="self_model",
        stage="selection", chat_id=snapshot.scope_chat_id,
        status=f"applied={len(applied)}:rejected={len(rejected)}")
    return BehaviorFrame(
        snapshot_version=snapshot.version,
        scope_chat_id=snapshot.scope_chat_id,
        addressee=addressee,
        agent_id=snapshot.agent_id,
        bot_user_id=snapshot.bot_user_id,
        self_presentation_mode=snapshot.self_presentation_mode,
        is_aware_ai=(snapshot.is_aware_ai.effective(True)
                     and not snapshot.is_aware_ai.is_error),
        applied_rules=tuple(applied),
        positions=positions,
        mood=snapshot.state,
        factual_constraints=constraints,
        scoped_request=scoped,
        rejected_rules=tuple(rejected),
        stale=snapshot.stale,
        fallback=snapshot.fallback,
        created_at=ts,
    )


def frame_signature(frame: BehaviorFrame) -> str:
    """Стабильный сигнатурный хеш кадра (кеш стабильного префикса, D7)."""
    material = "\x1f".join(
        [frame.version, frame.self_presentation_mode,
         f"rules={len(frame.applied_rules)}",
         f"stale={frame.stale}"] +
        [f"{r.rule_id}:{r.dimension}:{r.version}:{r.source}"
         for r in frame.applied_rules])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


# Новая формулировка False (D3): ЗАМЕНЯЕТ абсолютный запрет
# `_NO_AI_DISCLOSURE_BLOCK` в точке сборки (не дописывает противоположное
# в конец; §28.2 `:1522`/`:1525`).
SELF_MODEL_FALSE_BLOCK = (
    "Ты держишься заданного образа и не вставляешь техническое "
    "самоописание без повода. Техническая идентичность сохраняется: при "
    "прямом вопросе допускается явное разграничение образа и реализации — "
    "без обязательной ложной биографии и без выдуманных встреч, телесных "
    "действий или выполненных инструментов."
)

# Минимальная тех-идентичность (A58): пустая персона + aware.
_EMPTY_AWARE_LINE = (
    "Ты — цифровой собеседник в Telegram: общаешься текстом, опираешься "
    "на доступную память и инструменты.")


def render_frame_block(frame: BehaviorFrame, *, name: str = "",
                       biography: str = "", overrides: str = "",
                       is_aware_ai: bool | None = None,
                       include_static: bool = True) -> str:
    """Рендер кадра в точке сборки (детерминированный; D3): статика персоны +
    правила во 2-м лице (≠ цитат) + A58-минимум; False-формулировка
    ЗАМЕНЯЕТ старый запрет. Awareness — из кадра (snapshot effective);
    аргумент `is_aware_ai` — переопределение для прямых вызовов. Stale →
    правила/настроение/позиции НЕ рендерятся (fallback честен). Технические
    вызовы этот блок не получают."""
    lines: list[str] = []
    if include_static:
        if name:
            lines.append(f"Имя: {name}")
        if biography:
            lines.append(f"Биография: {biography}")
        if overrides:
            lines.append(f"Характер: {overrides}")
    aware = frame.is_aware_ai if is_aware_ai is None else bool(is_aware_ai)
    if not frame.stale:
        if frame.applied_rules:
            lines.append("Правила характера (применяй по ситуации):")
            for rule in frame.applied_rules:
                lines.append(f"• {rule.instruction}")
        if frame.scoped_request:
            lines.append("Разовая просьба к этому ответу: "
                         + "; ".join(frame.scoped_request))
        if frame.positions:
            lines.append("Твои позиции (мнения, не факты): "
                         + " ".join(f"• {p.text}" for p in frame.positions))
        if frame.mood is not None:
            lines.append(f"Текущее настроение (обратимо): {frame.mood.text}")
        if frame.factual_constraints:
            lines.append("Проверенные ограничения фактов: "
                         + "; ".join(frame.factual_constraints))
    if not lines:
        # A58: пустая персона → различимое поведение, не пустая строка.
        if frame.self_presentation_mode == MODE_AWARE:
            lines.append(_EMPTY_AWARE_LINE)
        else:
            lines.append("Ты отвечаешь в заданном образе, без технических "
                         "отступлений.")
    block = "<Persona>\n" + "\n".join(lines) + "\n</Persona>"
    # H-1 (rework): контроль по ВЫЧИСЛЕННОМУ aware (эффективное значение кадра/
    # override), а не по параметру-переопределению — иначе точка сборки без
    # параметра (`bot_persona.build_persona_prompt_block`) молча дописывала
    # FALSE-формулировку даже при is_aware_ai=True (§28.2 `:1522`/`:1525`).
    if not aware:
        block = block + "\n" + SELF_MODEL_FALSE_BLOCK
    return block


# ═══ T-5084: фоновый идемпотентный разбор persona_traits (D8) ═══════════════

LEGACY_PARSE_JOB_KIND = "legacy_traits_parse"
LEGACY_PARSE_OWNER = "mca18"
LEGACY_PARSE_COALESCE_KEY = "legacy_traits_parse:global"
LEGACY_PARSE_BATCH_MAX = 200


def legacy_parse_enabled() -> bool:
    """K3: фоновый разбор `persona_traits` (env-only, default ON)."""
    return bool(mca_gates.legacy_traits_migration_enabled())


async def run_legacy_traits_parse(db, *, limit: int | None = None,
                                  now: int | None = None) -> dict:
    """Идемпотентный разбор PG `persona_traits` → наблюдения/правила.

    * повтор = no-op по `legacy_ref` (FIFO persona_traits не порождает
      дублей; observation хранит raw дословно — источник не теряется);
    * source_refs — только указатели РЕАЛЬНОГО происхождения
      (`legacy_trait:{pg_id}`; фабрикация сообщений запрещена, `:1582`);
    * без доказанного субъекта (source≠manual) → candidate/`legacy_unverified`
      (НЕ active); ручная черта — основание = действие владельца;
    * dimension выводится детерминированно из текста (`infer_dimension`,
      закрытый набор 8 имён; нет совпадения → кандидат с причиной, H-2);
    * chat→global НЕ выполняется (отсутствие chat_id не доказывает
      универсальность; повышение — явное правило + обезличивание);
    * K3 OFF → честный skip; bounded batch; PG недоступен → failed-счётчик."""
    if not legacy_parse_enabled():
        mca_events.emit_mca_event(
            "self_model", outcome="skipped", component="self_model",
            stage="observation_read", reason_code="self_model_disabled",
            status="legacy_parse_disabled")
        return {"status": "disabled", "parsed": 0, "skipped": 0}
    pool = None
    try:
        from services import bot_persona
        pool = bot_persona._persona_pool()
    except Exception:
        pool = None
    if pool is None:
        mca_events.emit_mca_event(
            "self_model", outcome="failed", level="WARN",
            component="self_model", stage="observation_read",
            reason_code="self_model_unavailable", status="pg_unavailable")
        return {"status": "pg_unavailable", "parsed": 0, "skipped": 0}
    batch = max(1, int(limit or LEGACY_PARSE_BATCH_MAX))
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, chat_id, trait, source, created_at FROM "
                "persona_traits ORDER BY id DESC LIMIT $1", batch)
    except Exception:
        logger.warning("[mca18] legacy traits read failed", exc_info=True)
        mca_events.emit_mca_event(
            "self_model", outcome="failed", level="WARN",
            component="self_model", stage="observation_read",
            reason_code="self_model_unavailable", status="pg_read_failed")
        return {"status": "pg_unavailable", "parsed": 0, "skipped": 0}
    identity = await db.get_self_identity()
    if not identity or not identity.get("agent_id"):
        return {"status": "no_identity", "parsed": 0, "skipped": 0}
    agent_id = str(identity["agent_id"])
    parsed = 0
    skipped = 0
    unverified = 0
    for row in (rows or []):
        legacy_id = int(row["id"])
        if await db.observation_exists_by_legacy_ref(legacy_id):
            skipped += 1
            continue
        text = str(row["trait"] or "").strip()
        if not text:
            skipped += 1
            continue
        source = str(row["source"] or "deep_sleep")
        chat_id = row["chat_id"]
        ts = int(row["created_at"] or time.time())
        obs_id = await record_trait_observation(
            db, agent_id=agent_id, text=text,
            source_refs=(f"legacy_trait:{legacy_id}",),
            subject_status="self" if source == "manual" else "ambiguous",
            chat_id=chat_id, observed_at=ts, legacy_ref=legacy_id,
            dimension=infer_dimension(text))
        if obs_id is None:
            skipped += 1
            continue
        parsed += 1
        # Ручная черта: основание = действие владельца → при приведённом
        # dimension активируется сразу (rework H-2: детерминированный маппинг
        # текста в закрытый набор; нет совпадения → НЕприведённый кандидат,
        # исполняемого правила нет). Остальной legacy → candidate/
        # `legacy_unverified` (НЕ active; observation — носитель
        # кандидат-состояния; весь архив до включения перерабатывать не
        # требуется).
        if source == "manual":
            await promote_observation(db, obs_id, scope_chat_id=None)
        else:
            unverified += 1
            mca_events.emit_mca_event(
                "self_model", outcome="skipped", component="self_model",
                stage="candidate_compile",
                reason_code="legacy_trait_unverified",
                entity_ids=[f"legacy_trait:{legacy_id}"])
    mca_events.emit_mca_event(
        "self_model", outcome="success", component="self_model",
        stage="observation_read", status=f"parsed={parsed}:skipped={skipped}")
    return {"status": "ok", "parsed": parsed, "skipped": skipped,
            "unverified": unverified}


async def _observation_row(db, observation_id: int):
    cursor = await db.db.execute(
        "SELECT * FROM mca_trait_observations WHERE id = ?",
        (int(observation_id),))
    return await cursor.fetchone()
