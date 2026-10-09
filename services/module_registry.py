"""ASAP 7 (F3, §3.1/§3.2/§3.3) — канонический реестр продуктовых модулей.

ЕДИНЫЙ Python-источник ModuleSpec (§4.4 ТЗ): frontend получает реестр через
существующий `GET /api/config` (аддитивный ключ ответа ``modules``),
`MODULES` в web/app.js обогащается/дополняется записями реестра при наличии,
fallback — текущий hardcoded список (Δ риска = 0; §3.1).

Инварианты (тесты `tests/test_asap7_module_registry.py`):
* **M4 (drift)**: каждый ProductModuleSpec обязан иметь master_param —
  существующий ключ каталога (`param_catalog.REGISTRY`), settings_groups ⊆
  GROUPS, непустые status_source/help_anchor — иначе RED;
* **M2 (inventory)**: каждый env-kill-switch из `mca_gates.KILL_SWITCHES`
  маппится на registry-запись (MODULE_ENV_GATES) ИЛИ на явную
  INFRASTRUCTURE_RATIONALE-группу. 85 env-флагов НЕ превращаются в чекбоксы:
  rationale-таблица — легальный исход для maintenance/infra (§3.1).

§3.3 — общий паттерн toggle: `effective_gate(module_id) ->
(requested, effective, source)`::

    env_emergency OFF → effective OFF, source="emergency_env"  (env важнее UI)
    product toggle OFF → effective OFF, source="product_toggle"
    оба ON → effective ON, source="both"

Паттерн обязателен для Initiative и всех новых product toggles (F4).
"""
from __future__ import annotations

import dataclasses

from config.settings import settings

# Ленивый импорт внутри функций: services.hot_config не импортирует services
# на уровне модуля → цикла нет; кэш не инициализирован (тесты) → дефолт.


@dataclasses.dataclass(frozen=True)
class ModuleSpec:
    """Запись реестра модулей (поля — §4.4 ТЗ, ASAP 7)."""

    id: str                              # slug без префикса `mod_`
    title: str
    parent_id: str | None                # None = top-level карточка
    description: str                     # «на что влияет» простым русским
    master_param: str                    # pg-ключ каталога (обязателен, M4)
    runtime_gate: str                    # "global" | "per_chat"
    settings_groups: tuple[str, ...]     # ⊆ GROUPS (M4)
    model_slots: tuple[str, ...] = ()    # группы models/keys-слотов (или ())
    status_source: str = ""              # якорь статуса (M4: непустой)
    analytics_anchor: str = ""           # процесс/узел analytics (mca-17c)
    help_anchor: str = ""                # якорь словаря справки (M4: непустой)
    visibility: str = "visible"          # visible | advanced | hidden
    classification: str = "product_module"
    # product_module | submodule | infrastructure | maintenance
    rationale: str = ""                  # почему так классифицирован
    # ASAP 7 F4: config-вкладка поверхности подмодуля ("" → конвенция
    # mod_<id>; подмодули живут на существующих вкладках родителя —
    # новых вкладок/menu-freeze нет).
    config_tab: str = ""


# ── Реестр (аддитивный; F4 добавляет записи БЕЗ изменения каркаса) ──────────
MODULE_REGISTRY: dict[str, ModuleSpec] = {}


def _register(spec: ModuleSpec) -> ModuleSpec:
    if spec.id in MODULE_REGISTRY:
        raise ValueError(f"duplicate module id: {spec.id}")
    MODULE_REGISTRY[spec.id] = spec
    return spec


# mca-09 (аудит P7-C §1.2/§2): Initiative — Product Module, top-level карточка
# «Инициатива» (tab mod_initiative); master `flags.initiative_enabled`
# (каталог, default ON), effective = AND с env `MCA_INTENTS_ENABLED` (§3.2).
_register(ModuleSpec(
    id="initiative",
    title="Инициатива",
    parent_id=None,
    description=("Проактивные намерения: бот сам возвращается к открытым "
                 "вопросам и напоминаниям (heartbeat, решения, recheck)."),
    master_param="flags.initiative_enabled",
    runtime_gate="global",
    settings_groups=("flags_intent", "limits_intent"),
    model_slots=(),
    status_source="status_service.intent_snapshot",
    analytics_anchor="intent.initiative",
    help_anchor="Намерение",
    visibility="visible",
    classification="product_module",
    rationale=("mca-09/ADR-1028-16: самостоятельное проактивное поведение, "
               "включаемое/выключаемое, есть параметры (аудит P7-C-3: "
               "orphan без карточки/настроек — закрыто F3)"),
))

# ═══ ASAP 7 (F4, §3.2): оставшиеся orphans — подмодули (аудит P7-C-5) ═══════
# Родители — существующие поверхности («Память» = вкладка memory_rag /
# nav-раздел памяти; «Характер» = Persona/Досье): НОВЫХ top-level карточек
# и вкладок нет (§4.2 «не делать 100 карточек»; menu-freeze не растёт).

# Stories / Episodes → Submodule «Память»; мастер-ось — read-контур витрины.
_register(ModuleSpec(
    id="stories",
    title="Истории и эпизоды",
    parent_id="memory",
    description=("Витрина «Истории чата», действия с историями и жизненный "
                 "цикл эпизодов (мастер, фасад компилятора, продолжение, "
                 "backfill)."),
    master_param="flags.stories_vitrina_enabled",
    runtime_gate="global",
    settings_groups=("flags_stories",),
    model_slots=(),
    status_source="status_service «Истории чата» + web/api/stories",
    analytics_anchor="stories.vitrina",
    help_anchor="Истории",
    visibility="visible",
    classification="submodule",
    config_tab="memory_rag",
    rationale=("mca-12/mca-05 (аудит P7-C-5, §3.2): управляемая витрина/"
               "мутации/эпизоды — подмодуль «Памяти»; env-рубильники K1/K2 "
               "и эпизодный мастер — аварийные оси (AND-гейт mca_gates)."),
))

# SelfModel / Character evolution → Submodule «Характер» (parent Persona/
# Досье); поверхность — вкладка permsoc, Advanced-размещение группы.
_register(ModuleSpec(
    id="character",
    title="Характер (SelfModel)",
    parent_id="persona",
    description=("Эволюция характера: модель себя, правила черт, миграция "
                 "legacy-черт, слои и речь характера, scope стиля, "
                 "форм-гард постобработки."),
    master_param="flags.self_model_enabled",
    runtime_gate="global",
    settings_groups=("flags_character",),
    model_slots=(),
    status_source="mca17c self_model + adjacentSelfModelLine (Статус)",
    analytics_anchor="self_model.snapshot",
    help_anchor="Динамические черты",
    visibility="advanced",
    classification="submodule",
    config_tab="permsoc",
    rationale=("mca-18 (аудит P7-C-5, §3.2): 7 env-only осей без UI-"
               "владельца — подмодуль «Характер» родителя Persona/Досье; "
               "группа Advanced (тонкие контуры, обычно не трогать)."),
))

# Experience / Lessons → Submodule «Память»; настройки СУЩЕСТВУЮТ
# (memory_experience) — регистрации/родителя только, без дублей.
_register(ModuleSpec(
    id="experience",
    title="Опыт и уроки",
    parent_id="memory",
    description=("Банк проверенного опыта: запись эпизодов, уроки и "
                 "пакетный разбор (уроки не меняют правила бота)."),
    master_param="memory.experience_learning_enabled",
    runtime_gate="global",
    settings_groups=("memory_experience",),
    model_slots=(),
    status_source="status_service data-experience лента",
    analytics_anchor="self_learning.run",
    help_anchor="Урок",
    visibility="visible",
    classification="submodule",
    config_tab="memory_rag",
    rationale=("mca-16 (аудит P7-C-5, §3.2): настройки есть (hot-ключ читает "
               "mca_experience_jobs), registration/родителя не было; "
               "env K1–K4 — аварийные оси (MODULE_ENV_GATES)."),
))

# Random / Quantum → Submodule «Случайность» (shared, parent «Память»);
# настройки СУЩЕСТВУЮТ (memory_random + random.uses + keys_random).
_register(ModuleSpec(
    id="random",
    title="Случайность",
    parent_id="memory",
    description=("Источник случайности (квантовый ANU или локальный), "
                 "честный откат, вероятности исследования и разрешения "
                 "применений. Shared: спонтанность, сон, инициатива."),
    master_param="",
    runtime_gate="global",
    settings_groups=("memory_random",),
    model_slots=("keys_random",),
    status_source="status_service «Источник случайности»",
    analytics_anchor="random.source",
    help_anchor="Источник случайности",
    visibility="visible",
    classification="submodule",
    config_tab="mod_sleep",
    rationale=("mca-10a/10b (аудит P7-C-5, §3.2): shared subsystem — parent "
               "«Память», owner-карточка и ссылки из Initiative/Sleep. "
               "no master: мастера-тумблера в каталоге нет и дублировать "
               "env-ось MCA_RANDOM_SOURCE_ENABLED нельзя — мастер честно "
               "показывается как env-ось в гейте подкарточки."),
))

# master_param → env-kill-switch (raw-ось для §3.3; composite AND живёт в
# mca_gates — реестр считает source по СЫРЫМ значениям каждой оси).
ENV_GATES: dict[str, str] = {
    "initiative": "MCA_INTENTS_ENABLED",
    # ASAP 7 F4 (§3.2): подмодули. Stories — мастер read-контура витрины
    # (эпизодный мастер MCA_EPISODES_ENABLED — самостоятельная ось, его
    # тумблер показан в настройках подкарточки); Experience — env-мастер
    # K1 (requested-ось — существующий hot-ключ memory.experience_learning_enabled,
    # читается mca_experience_jobs); Random — мастера-тумблера НЕТ (мастер —
    # env-ось, «no master» rationale в записи).
    "stories": "MCA_STORIES_VITRINA_ENABLED",
    "character": "MCA_SELF_MODEL_ENABLED",
    "experience": "MCA_EXPERIENCE_LESSONS_ENABLED",
    "random": "MCA_RANDOM_SOURCE_ENABLED",
}

# Дефолты product-осей при отсутствии ключа в PG (кэш не поднят / до сида).
PRODUCT_DEFAULTS: dict[str, bool] = {
    "flags.initiative_enabled": True,
    "flags.stories_vitrina_enabled": True,
    "flags.self_model_enabled": True,
    "memory.experience_learning_enabled": True,
}


def _product_requested(master_param: str) -> bool:
    """Requested-ось: каталоговый тумблер (hot) → дефолт (никогда не бросает).
    Пустой master_param («no master», F4-random) → True (ось одна — env)."""
    if not master_param:
        return True
    try:
        from services import hot_config
        return bool(hot_config.get(master_param,
                                   PRODUCT_DEFAULTS.get(master_param, True)))
    except Exception:      # pragma: no cover — fail-open (старое поведение)
        return bool(PRODUCT_DEFAULTS.get(master_param, True))


def env_enabled(module_id: str) -> bool:
    """Сырая env-ось (emergency kill-switch; читается per-call, не кешируется)."""
    gate = ENV_GATES.get(module_id)
    if not gate:
        return True
    return bool(getattr(settings, gate, True))


def effective_gate(module_id: str) -> tuple[bool, bool, str]:
    """§3.3: `(requested, effective, source)`.

    source: ``emergency_env`` (env OFF важнее UI) | ``product_toggle``
    (тумблер OFF) | ``both`` (оба ON). Никогда не бросает."""
    spec = MODULE_REGISTRY.get(module_id)
    env = env_enabled(module_id)
    requested = _product_requested(spec.master_param) if spec else True
    if not env:
        return (requested, False, "emergency_env")
    if not requested:
        return (requested, False, "product_toggle")
    return (requested, True, "both")


def gate_snapshot(module_id: str) -> dict:
    """Плоский снимок гейта для status/UI (аддитивные поля; никогда не бросает)."""
    spec = MODULE_REGISTRY.get(module_id)
    requested, effective, source = effective_gate(module_id)
    return {
        "module_id": module_id,
        "master_param": spec.master_param if spec else "",
        "env_param": ENV_GATES.get(module_id, ""),
        "requested": requested,
        "effective": effective,
        "source": source,
        "env_enabled": env_enabled(module_id),
    }


def registry_for_frontend() -> list[dict]:
    """Сериализация реестра для аддитивного ключа ``modules`` ответа
    `GET /api/config` (§3.1: frontend рендерит из registry при наличии записи,
    fallback — hardcoded список; порядок детерминированный).

    F4: + ``config_tab`` (поверхность подмодуля) и + ``gate`` — снимок
    `gate_snapshot` на момент запроса (requested/effective/source + env-ось),
    чтобы подкарточки без собственного /api/status-блока показывали честный
    effective-дисплей (§4.3) из уже существующего носителя (routes.py не
    менялся)."""
    out: list[dict] = []
    for spec in MODULE_REGISTRY.values():
        out.append({
            "id": spec.id,
            "title": spec.title,
            "parent_id": spec.parent_id,
            "description": spec.description,
            "master_param": spec.master_param,
            "runtime_gate": spec.runtime_gate,
            "settings_groups": list(spec.settings_groups),
            "model_slots": list(spec.model_slots),
            "status_source": spec.status_source,
            "analytics_anchor": spec.analytics_anchor,
            "help_anchor": spec.help_anchor,
            "visibility": spec.visibility,
            "classification": spec.classification,
            "rationale": spec.rationale,
            "config_tab": spec.config_tab or f"mod_{spec.id}",
            # Производные поверхности фронта (tab/route — конвенция mod_*)
            "tab": f"mod_{spec.id}",
            "route": f"#/modules/{spec.id}",
            "gate": gate_snapshot(spec.id),
        })
    return out


def validate_spec(spec: ModuleSpec) -> list[str]:
    """M4 (drift, §3.1): список нарушений обязательных полей (пустой → ок).

    ProductModuleSpec (classification == "product_module") обязан иметь
    master_param — существующий мигрируемый ключ каталога; подмодули —
    тоже, ЛИБО явный «no master»-rationale (бриф F4: «master_param из
    каталога (или explicit no master rationale)»). settings_groups ⊆ GROUPS,
    status_source/help_anchor/rationale непусты, classification/visibility —
    закрытые множества."""
    errors: list[str] = []
    if spec.classification not in ("product_module", "submodule",
                                   "infrastructure", "maintenance"):
        errors.append(f"{spec.id}: classification={spec.classification!r}")
    if spec.visibility not in ("visible", "advanced", "hidden"):
        errors.append(f"{spec.id}: visibility={spec.visibility!r}")
    if not spec.status_source:
        errors.append(f"{spec.id}: пустой status_source")
    if not spec.help_anchor:
        errors.append(f"{spec.id}: пустой help_anchor")
    if not spec.rationale:
        errors.append(f"{spec.id}: пустой rationale")
    try:
        from services import param_catalog as pc
        group_ids = {g.id for g in pc.GROUPS}
        unknown = set(spec.settings_groups) - group_ids
        if unknown:
            errors.append(f"{spec.id}: группы вне GROUPS: {sorted(unknown)}")
        if spec.master_param:
            entry = pc.get_by_pg_key(spec.master_param)
            if entry is None:
                errors.append(f"{spec.id}: master_param "
                              f"{spec.master_param} вне каталога")
            elif not entry.migratable:
                errors.append(f"{spec.id}: master_param "
                              f"{spec.master_param} не migratable")
        elif spec.classification == "product_module":
            errors.append(f"{spec.id}: product_module без master_param")
        elif "no master" not in spec.rationale.lower():
            errors.append(f"{spec.id}: пустой master_param без явного "
                          f"«no master»-rationale")
    except Exception as exc:    # pragma: no cover — каталог обязан читаться
        errors.append(f"{spec.id}: каталог недоступен: {exc}")
    return errors


# ── M2: ownership env-kill-switches (aудит P7-C §1.1; KILL_SWITCHES = 85) ───
# Каждый operator-facing gate маппится на registry-запись (MODULE_ENV_GATES /
# группы ниже) ИЛИ на явную rationale-группу. 85 env-флагов НЕ становятся
# чекбоксами: rationale — легальный исход для maintenance/infra (§3.1).

#: env-гейты, принадлежащие зарегистрированным продуктовым модулям.
#: F4 (§3.2): подмодули stories/character/experience/random получили owner —
#: их оси перенесены из rationale-группы «submodule→F4» (аудит P7-C-5).
MODULE_ENV_GATES: dict[str, tuple[str, ...]] = {
    "initiative": (
        "MCA_INTENTS_ENABLED",             # K1 мастер
        "MCA_INTENT_HEARTBEAT_ENABLED",    # K2 due-тик
        "MCA_INTENT_DECISION_ENABLED",     # K3 решения
        "MCA_SEND_RECHECK_ENABLED",        # K4 recheck отправки
    ),
    "stories": (
        "MCA_STORIES_VITRINA_ENABLED",     # K1 read-контур витрины
        "MCA_STORIES_MANAGE_ENABLED",      # K2 мутации
        "MCA_EPISODES_ENABLED",            # мастер эпизодов
        "MCA_EPISODES_COMPILER_FACADE_ENABLED",
        "MCA_EPISODES_CONTINUATION_ENABLED",
        "MCA_EPISODES_BACKFILL_ENABLED",
    ),
    "character": (
        "MCA_SELF_MODEL_ENABLED",          # K1 мастер
        "MCA_TRAIT_RULES_ENABLED",         # K2
        "MCA_LEGACY_TRAITS_MIGRATION_ENABLED",  # K3
        "MCA_CHARACTER_LAYERS_ENABLED",
        "MCA_CHARACTER_SPEECH_ENABLED",
        "MCA_STYLE_SCOPE_ENABLED",
        "MCA_POSTPROCESS_FORM_GUARD_ENABLED",
    ),
    "random": (
        "MCA_RANDOM_SOURCE_ENABLED",       # мастер (env-ось; no master-тумблер)
        "MCA_RANDOM_QUANTUM_ENABLED",
        "MCA_RANDOM_REFILL_ENABLED",
        "MCA_RANDOM_EXPLORATION_ENABLED",
        "MCA_RANDOM_USES_ENABLED",
    ),
    "experience": (
        "MCA_EXPERIENCE_LESSONS_ENABLED",  # K1 мастер
        "MCA_EXPERIENCE_REVIEW_ENABLED",   # K3
        "MCA_EXPERIENCE_CONTEXT_ENABLED",  # K4
        "MCA_EXPERIENCE_FEEDBACK_ENABLED", # K2
    ),
}

#: (класс решения, краткий rationale, exact-имена) — НЕ зарегистрированные
#: модулями гейты. Тест M2 проверяет: объединение с MODULE_ENV_GATES покрывает
#: `mca_gates.KILL_SWITCHES` без пропусков и дублей.
INFRASTRUCTURE_RATIONALE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "submodule→registered (остаток: Vision)",
        "Orphan-фичи волны P7-C (аудит §1.2): Stories/Episodes, "
        "SelfModel/Character (7 осей), Random/Quantum (5), Experience (4) "
        "ЗАРЕГИСТРИРОВАНЫ F4 (MODULE_ENV_GATES; настройка/AND-гейты — "
        "param_catalog flags_stories/flags_character + mca_gates §3.3). "
        "Остаток — Vision (4): регистрация вне объёма F4 (brief Wave 3), "
        "env-рубильники остаются аварийными (default ON).",
        (
            "MCA_VISION_ENABLED", "MCA_VISION_AUTO_ENABLED",
            "MCA_VISION_BACKFILL_ENABLED", "MCA_VISION_TOOL_ENABLED",
        ),
    ),
    (
        "submodule-registered",
        "Temporal Factcheck — эталон submodule (parent mod_factcheck, "
        "catalog-тумблер temporal.tool_enabled существует; env — аварийные); "
        "Summary singleflight — infra контура mod_summary; stats-intent — "
        "дет. пре-блок Direct (tool в наборе нет).",
        (
            "MCA_TEMPORAL_FACTCHECK_ENABLED",
            "MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED",
            "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED",
            "MCA_SUMMARY_SINGLEFLIGHT_ENABLED",
            "MCA_STATS_INTENT_ENABLED",
        ),
    ),
    (
        "maintenance/infrastructure (dossier/embeddings)",
        "Пересборка Досье/прогрев/реклассификация и активация эмбеддинг-"
        "генерации — maintenance/infra с operator-facing настройками в "
        "родителе «Память» (аудит §1.2: Embeddings/GraphRAG = Infrastructure, "
        "Dossier rebuild = Maintenance; раскладка Advanced — F4, M2-аудит).",
        (
            "MCA_DOSSIER_BACKGROUND_PASS_ENABLED",
            "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED",
            "MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED",
            "MCA_DOSSIER_REBUILD_ENABLED",
            "MCA_DOSSIER_RECLASSIFY_ENABLED",
            "MCA_DOSSIER_STAGING_ACTIVATION_ENABLED",
            "MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED",
        ),
    ),
    (
        "infrastructure/maintenance",
        "Infra/Maintenance (OFF = бит-в-бит baseline, документированный "
        "паритет; operator-facing UI не требуется — политика mca-18/19/20, "
        "release-маркеры «KS — 0 env-оверрайдов»): миграции/транзакции/"
        "супервизор задач/контракты событий/телеметрия/идентичность "
        "сообщений/fetch-безопасность/provenance/атрибуция/retrieval/"
        "кеш/observability/джобы/dream-оси/фин-лимиты/гарды ответов.",
        (
            "MCA_SCHEMA_MIGRATIONS_ENABLED", "MCA_TX_OWNERSHIP_ENABLED",
            "MCA_TASK_SUPERVISOR_ENABLED", "MCA_EVENT_CONTRACT_ENABLED",
            "MCA_TELEMETRY_STORE_ENABLED", "MCA_TELEMETRY_SPOOL_ENABLED",
            "MCA_MESSAGE_IDENTITY_ENABLED",
            "MCA_MESSAGE_REVISION_TRACKING_ENABLED",
            "MCA_SAFE_FETCH_ENABLED", "MCA_EGRESS_GUARD_ENABLED",
            "MCA_PROVENANCE_ENABLED", "MCA_FACT_ATTRIBUTION_ENABLED",
            "MCA_CANONICAL_ATTRIBUTION_ENABLED",
            "MCA_EVIDENCE_RECONSTRUCTION_ENABLED",
            "MCA_EVIDENCE_BUNDLE_ENABLED",
            "MCA_RETRIEVAL_CONTEXT_ENABLED",
            "MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED",
            "MCA_CONTEXT_ANSWER_CACHE_ENABLED",
            "MCA_TYPED_RERANKER_ENABLED",
            "MCA_OBSERVABILITY_ENABLED", "MCA_TRACE_SPAN_ENABLED",
            "MCA_PROCESS_REGISTRY_ENABLED", "MCA_JOB_LIFECYCLE_ENABLED",
            "MCA_HEARTBEAT_WATCHDOG_ENABLED", "MCA_INCIDENTS_ENABLED",
            "MCA_INCIDENT_PUSH_ENABLED", "MCA_BOT_OUTPUT_LEDGER_ENABLED",
            "MCA_CHAT_STATISTICS_ENABLED", "MCA_COST_ACCOUNTING_ENABLED",
            "MCA_MONEY_LIMITS_ENABLED", "MCA_NUMERIC_CLAIM_GUARD_ENABLED",
            "MCA_RESPONSE_FRESHNESS_GUARD_ENABLED",
            "MCA_TOOL_CHAIN_STAGES_ENABLED",
            "MCA_TOOL_DELIVERY_GUARD_ENABLED", "MCA_TOOL_RESULT_ENABLED",
            "MCA_CORRECTION_REVALIDATION_ENABLED",
            "MCA_DREAM_EVIDENCE_TYPING_ENABLED",
            "MCA_DREAM_GATE_RESOLVER_ENABLED",
            "MCA_DREAM_HISTORICAL_PROFILE_ENABLED",
            "MCA_DREAM_QUOTAS_SPLIT_ENABLED",
            "MCA_DREAM_RANDOM_EXPLORE_ENABLED",
            "MCA_DREAM_REVISION_QUEUE_ENABLED",
            "MCA_DREAM_RUN_REPORTS_ENABLED",
        ),
    ),
)
