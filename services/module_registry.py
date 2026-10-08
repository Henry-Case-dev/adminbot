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

# master_param → env-kill-switch (raw-ось для §3.3; composite AND живёт в
# mca_gates — реестр считает source по СЫРЫМ значениям каждой оси).
ENV_GATES: dict[str, str] = {
    "initiative": "MCA_INTENTS_ENABLED",
}

# Дефолты product-осей при отсутствии ключа в PG (кэш не поднят / до сида).
PRODUCT_DEFAULTS: dict[str, bool] = {
    "flags.initiative_enabled": True,
}


def _product_requested(master_param: str) -> bool:
    """Requested-ось: каталоговый тумблер (hot) → дефолт (никогда не бросает)."""
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
    fallback — hardcoded список; порядок детерминированный)."""
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
            # Производные поверхности фронта (tab/route — конвенция mod_*)
            "tab": f"mod_{spec.id}",
            "route": f"#/modules/{spec.id}",
        })
    return out


# ── M2: ownership env-kill-switches (aудит P7-C §1.1; KILL_SWITCHES = 85) ───
# Каждый operator-facing gate маппится на registry-запись (MODULE_ENV_GATES /
# группы ниже) ИЛИ на явную rationale-группу. 85 env-флагов НЕ становятся
# чекбоксами: rationale — легальный исход для maintenance/infra (§3.1).

#: env-гейты, принадлежащие зарегистрированным продуктовым модулям.
MODULE_ENV_GATES: dict[str, tuple[str, ...]] = {
    "initiative": (
        "MCA_INTENTS_ENABLED",             # K1 мастер
        "MCA_INTENT_HEARTBEAT_ENABLED",    # K2 due-тик
        "MCA_INTENT_DECISION_ENABLED",     # K3 решения
        "MCA_SEND_RECHECK_ENABLED",        # K4 recheck отправки
    ),
}

#: (класс решения, краткий rationale, exact-имена) — НЕ зарегистрированные
#: модулями гейты. Тест M2 проверяет: объединение с MODULE_ENV_GATES покрывает
#: `mca_gates.KILL_SWITCHES` без пропусков и дублей.
INFRASTRUCTURE_RATIONALE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "submodule→F4",
        "Orphan-фичи волны P7-C (аудит §1.2): Stories/Episodes, "
        "SelfModel/Character (7 осей), Random/Quantum (5), Experience (4), "
        "Vision (5) — регистрация/настройки выполняет F4 (BLOCKED_BY F3); "
        "env-рубильники остаются аварийными (default ON).",
        (
            "MCA_STORIES_VITRINA_ENABLED", "MCA_STORIES_MANAGE_ENABLED",
            "MCA_EPISODES_ENABLED", "MCA_EPISODES_COMPILER_FACADE_ENABLED",
            "MCA_EPISODES_CONTINUATION_ENABLED", "MCA_EPISODES_BACKFILL_ENABLED",
            "MCA_SELF_MODEL_ENABLED", "MCA_TRAIT_RULES_ENABLED",
            "MCA_LEGACY_TRAITS_MIGRATION_ENABLED",
            "MCA_CHARACTER_LAYERS_ENABLED", "MCA_CHARACTER_SPEECH_ENABLED",
            "MCA_STYLE_SCOPE_ENABLED", "MCA_POSTPROCESS_FORM_GUARD_ENABLED",
            "MCA_RANDOM_SOURCE_ENABLED", "MCA_RANDOM_QUANTUM_ENABLED",
            "MCA_RANDOM_REFILL_ENABLED", "MCA_RANDOM_EXPLORATION_ENABLED",
            "MCA_RANDOM_USES_ENABLED",
            "MCA_EXPERIENCE_LESSONS_ENABLED", "MCA_EXPERIENCE_REVIEW_ENABLED",
            "MCA_EXPERIENCE_CONTEXT_ENABLED", "MCA_EXPERIENCE_FEEDBACK_ENABLED",
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
