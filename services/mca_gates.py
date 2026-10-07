"""Раунд 10.27 (MCA Wave 0) — единый реестр kill-switch'ей волны 0.

Политика (ADR-1027-1 D7 / ADR-1027-3 D9; рамка `mca-round1027-arch-frames.md` §3):

* **env-only** `ClassVar[bool]` в `config/settings.py`, **default ON**;
* **резолв per-call** (значение читается при каждом обращении, не кешируется
  на импорте), **никогда не бросает**;
* **OFF = точный паритет baseline** — ровно прежнее поведение, без новых
  записей/эффектов;
* Δ каталога = 0 (`param_catalog.py` не меняется);
* существующие рубильники `DB_LOCK_RESILIENCE_ENABLED` (F0.5/ADR-1024-18),
  `AGENTIC_EVENTS_ENABLED` (ADR-1026-22 D3) **уважаются и не дублируются**.

ВАЖНО: имя модуля — `mca_gates` (не `feature_gates`), чтобы не конфликтовать
с существующим `services/feature_gates.py` (F-10 worker-budget gates).
"""
from __future__ import annotations

import dataclasses
import time

from config.settings import settings

# Sentinel: `memory` не передан → вывести из `worker.memory` (или None).
_UNSET = object()

# Реестр kill-switch'ей волны 0 (mca-14 / mca-01). Используется тестами
# политики (T-3759/T-3747) и release-manifest'ом: имя → (default, OFF-паритет).
KILL_SWITCHES: dict[str, tuple[bool, str]] = {
    "MCA_SCHEMA_MIGRATIONS_ENABLED": (
        True,
        "legacy-путь миграций (hardcoded `_migrate_*`), без runner/backup",
    ),
    "MCA_TX_OWNERSHIP_ENABLED": (
        True,
        "прежний `write_transaction`: rollback вне lock, отмена ожидающего "
        "может откатить общую connection (baseline-дефект §5.1 сохраняется "
        "по дизайну OFF)",
    ),
    "MCA_TASK_SUPERVISOR_ENABLED": (
        True,
        "без реестра/durable-очереди/coalescing (текущее поведение задач)",
    ),
    "MCA_EVENT_CONTRACT_ENABLED": (
        True,
        "события как сейчас (`emit_agentic_event` без start/outcome/durable)",
    ),
    "MCA_TELEMETRY_STORE_ENABLED": (
        True,
        "только структурный лог, без durable-персистенции (`mca_events`)",
    ),
    "MCA_MESSAGE_IDENTITY_ENABLED": (
        True,
        "legacy ingestion/импорт без канонической идентичности и source "
        "records (`save_smart_message`; паритет baseline 7165ff7)",
    ),
    "MCA_MESSAGE_REVISION_TRACKING_ENABLED": (
        True,
        "редакции без версионирования (текущее поведение baseline)",
    ),
    "MCA_SAFE_FETCH_ENABLED": (
        True,
        "legacy-путь загрузки (как сейчас, без SSRF-обвязки/лимитов-обёртки; "
        "паритет baseline)",
    ),
    "MCA_EGRESS_GUARD_ENABLED": (
        True,
        "без эквивалентного egress-контроля для подпроцессов/yt-dlp/прокси "
        "(legacy; паритет baseline)",
    ),
    "MCA_PROVENANCE_ENABLED": (
        True,
        "legacy-путь без типизированных SourceRef/EvidenceLink/статусов "
        "(новые записи/связи не создаются; паритет baseline)",
    ),
    "MCA_FACT_ATTRIBUTION_ENABLED": (
        True,
        "legacy-атрибуция фактов (`target=asker`, name-scope читатели, "
        "Layer B person_facts не сохраняются; паритет §8.3.2-baseline)",
    ),
    "MCA_EVIDENCE_RECONSTRUCTION_ENABLED": (
        True,
        "восстановление старых записей не запускается (прямо сохранённое "
        "происхождение по-прежнему фиксируется)",
    ),
    # ── mca-07 (ADR-1027-7 D12) ─────────────────────────────────────────────
    "MCA_RETRIEVAL_CONTEXT_ENABLED": (
        True,
        "legacy-путь retrieval/embedding (раздельные каналы без единого "
        "контракта; sha256(casefold+strip) + dim-проверка) — паритет baseline",
    ),
    "MCA_EVIDENCE_BUNDLE_ENABLED": (
        True,
        "legacy-сборка контекста без единого in-memory EvidenceBundle",
    ),
    "MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED": (
        True,
        "прежний `_apply_context_budget` (без полного учёта payload/"
        "адаптивности/protected spans)",
    ),
    "MCA_TYPED_RERANKER_ENABLED": (
        True,
        "прежний reranker (без типизированного списка ID; ошибка/пустой парс "
        "→ исходные кандидаты)",
    ),
    "MCA_SUMMARY_SINGLEFLIGHT_ENABLED": (
        True,
        "прежний fire-and-forget без singleflight/high-watermark/CAS",
    ),
    "MCA_CONTEXT_ANSWER_CACHE_ENABLED": (
        True,
        "прежний ответный кеш по одному нормализованному query/chat/user "
        "(text-replay) — паритет baseline; ON = context-keyed политика",
    ),
    # ── mca-17a (ADR-1027-8 D12) — ядро наблюдаемости ───────────────────────
    "MCA_OBSERVABILITY_ENABLED": (
        True,
        "OFF → паритет baseline целиком (без реестра/span/lifecycle/watchdog/"
        "инцидентов; `emit_mca_event`/ExecutionGraph как есть)",
    ),
    "MCA_PROCESS_REGISTRY_ENABLED": (
        True,
        "OFF → реестр процессов не публикуется/не регистрируется",
    ),
    "MCA_TRACE_SPAN_ENABLED": (
        True,
        "OFF → события без расширенных span-полей (только контракт MCA-13)",
    ),
    "MCA_JOB_LIFECYCLE_ENABLED": (
        True,
        "OFF → lifecycle/`partial`/`degraded`/linked job не вычисляются",
    ),
    "MCA_HEARTBEAT_WATCHDOG_ENABLED": (
        True,
        "OFF → нет watchdog/takeover/stale-детекта",
    ),
    "MCA_INCIDENTS_ENABLED": (
        True,
        "OFF → инциденты не группируются/не ведутся",
    ),
    "MCA_INCIDENT_PUSH_ENABLED": (
        True,
        "OFF → доставка инцидентов в миниапп выключена",
    ),
    "MCA_TELEMETRY_SPOOL_ENABLED": (
        True,
        "OFF → нет дискового spool/degraded-счётчика (structural fallback)",
    ),
    # ── mca-04b (ADR-1027-9 D13) — dossier rebuild ──────────────────────────
    "MCA_DOSSIER_REBUILD_ENABLED": (
        True,
        "legacy `run_dossier_rebuild` как сейчас (без нового контракта/"
        "состояний; паритет baseline)",
    ),
    "MCA_DOSSIER_BACKGROUND_PASS_ENABLED": (
        True,
        "фоновый проход по архиву не запускается",
    ),
    "MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED": (
        True,
        "read-time восстановление не запускается (инертен при "
        "MCA_EVIDENCE_RECONSTRUCTION_ENABLED=OFF)",
    ),
    "MCA_DOSSIER_RECLASSIFY_ENABLED": (
        True,
        "безопасная реклассификация накопленных данных не выполняется",
    ),
    "MCA_DOSSIER_STAGING_ACTIVATION_ENABLED": (
        True,
        "прямая запись как сейчас (без staging/generation)",
    ),
    "MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED": (
        True,
        "gate mca-07 FTS-only как сейчас (активация поколения не выполняется)",
    ),
    "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED": (
        True,
        "прежний namespace-отпечаток импорта (legacy_import_v1/v1-digest)",
    ),
    # ── mca-05 (ADR-1027-12 D13) — episodes/stories ─────────────────────────
    "MCA_EPISODES_ENABLED": (
        True,
        "legacy-путь целиком: `lore_stories`/компилятор/mca-07 канал работают "
        "как сегодня (пайплайн/backfill/фасад неактивны; паритет baseline)",
    ),
    "MCA_EPISODES_BACKFILL_ENABLED": (
        True,
        "фоновый backfill по архиву не запускается (инертен при master OFF)",
    ),
    "MCA_EPISODES_CONTINUATION_ENABLED": (
        True,
        "кандидаты/подтверждения продолжений не строятся (без новых склеек)",
    ),
    "MCA_EPISODES_COMPILER_FACADE_ENABLED": (
        True,
        "компилятор/mca-07 episode-канал как сегодня (legacy `lore_stories` "
        "без фасада нового store)",
    ),
    # ── mca-22 (ADR-1028-6 D10) — FINAL INTEGRATION: атрибуция/память/     ──
    #    freshness. Ровно 4 рубильника фичи; env-only, default ON, OFF =
    #    паритет baseline. В админ-UI не выносятся (§32).
    "MCA_CANONICAL_ATTRIBUTION_ENABLED": (
        True,
        "потребители читают/пишут как сегодня (существующие SELECT/записи); "
        "роль-колонки не используются; canonical envelope/projection, quote "
        "resolver, claim envelope, speaker≠subject, producer-validator, "
        "GraphRAG provenance enforcement и retrieval attribution недостижимы",
    ),
    "MCA_BOT_OUTPUT_LEDGER_ENABLED": (
        True,
        "`bot_replies` как сегодня (TTL-кеш); `mca_bot_outputs` не пишется/"
        "не читается; quote-priority 5 недоступна (лестница → 6/7)",
    ),
    "MCA_CORRECTION_REVALIDATION_ENABLED": (
        True,
        "фразы-триггеры коррекции обрабатываются как обычный диалог; "
        "существующие статусы не меняются",
    ),
    "MCA_RESPONSE_FRESHNESS_GUARD_ENABLED": (
        True,
        "текущее поведение: update-dedup/no-replay/duplicate guard/"
        "freshness retry/lineage-события неактивны; legacy text-dedup живёт "
        "под собственной политикой `MCA_CONTEXT_ANSWER_CACHE_ENABLED`",
    ),
    # ── mca-06 (ADR-1028-9 D1–D12) — sleep paradigms: 7 env-only рубильников ──
    # Послойный OFF = бит-в-бит 2.58.48 (soft-откат). Блоки B–H.
    "MCA_DREAM_GATE_RESOLVER_ENABLED": (
        True,
        "прежние ветки disabled/`master_off`-обобщённость, нули-при-ошибке "
        "счётчиков (точный код 2.58.48; §3)",
    ),
    "MCA_DREAM_HISTORICAL_PROFILE_ENABLED": (
        True,
        "прежний порядок `get_rag_facts` → top_k → возраст (`:1577–1590`; §4)",
    ),
    "MCA_DREAM_EVIDENCE_TYPING_ENABLED": (
        True,
        "прежние `source_ids`-only + `min_anchors=2` по числу якорей (§5, §8.1)",
    ),
    "MCA_DREAM_QUOTAS_SPLIT_ENABLED": (
        True,
        "прежний глобальный `count_deep_attempts` + общий cooldown (§6)",
    ),
    "MCA_DREAM_RUN_REPORTS_ENABLED": (
        True,
        "только прежний `_trace_deep`/лог; реестр — честный `not_run` (§7.2)",
    ),
    "MCA_DREAM_REVISION_QUEUE_ENABLED": (
        True,
        "пересмотр зависимых выводов не запускается (§8.4)",
    ),
    "MCA_DREAM_RANDOM_EXPLORE_ENABLED": (
        True,
        "исследование случайных периодов не выполняется (§8.7)",
    ),
    # ── mca-08 (ADR-1028-11 D10) блоки A+B: K1/K2 ───────────────────────────
    "MCA_CHARACTER_LAYERS_ENABLED": (
        True,
        "нет read-контекста слоёв/Character_Rules/character_block; ветка "
        "persona в direct/verbalizer как 2.58.54 (паритет baseline)",
    ),
    "MCA_CHARACTER_SPEECH_ENABLED": (
        True,
        "нет SpeechUnderstanding/<Speech_Understanding>/clarify; ответный "
        "путь как 2.58.54 (паритет baseline)",
    ),
    # ── mca-08 (ADR-1028-11 D10) блоки C+D: K3/K4 ──────────────────────────
    "MCA_STYLE_SCOPE_ENABLED": (
        True,
        "нет ingestion/прав/резолва/<Style_Requests>; скрытая /style "
        "неактивна; таблица mca_style_requests не читается/не пишется "
        "(паритет baseline 2.58.54)",
    ),
    "MCA_POSTPROCESS_FORM_GUARD_ENABLED": (
        True,
        "`verbalize_validated` как 2.58.54 (клише-loop+scrubber без "
        "form-гардов/fallback; новые параметры игнорируются)",
    ),
    # ── mca-15 (ADR-1028-12 D8): K1/K2/K3 ──────────────────────────────────
    "MCA_CHAT_STATISTICS_ENABLED": (
        True,
        "нет stats-режима/measurement/MetricResult; `query_chat_memory`/"
        "`_dig_into_lore`/`_dig_json_payload`/lore-агрегаты как 2.58.55 "
        "(включая «Найдено N упоминаний» и голый `total_mentions`)",
    ),
    "MCA_NUMERIC_CLAIM_GUARD_ENABLED": (
        True,
        "`verbalize_validated` без numeric-контракта; финальная сборка "
        "direct без гарда; новые параметры игнорируются (паритет 2.58.55)",
    ),
    "MCA_STATS_INTENT_ENABLED": (
        True,
        "классификатор/хинт/reason-коды интента не работают; intent-"
        "поведение как 2.58.55",
    ),
    # ── mca-11 (ADR-1028-13 D7): K1/K2/K3 блоков A+B (K4/K5 — блоки C/D) ──
    "MCA_TOOL_RESULT_ENABLED": (
        True,
        "envelope legacy 2.58.56 байт-в-байт (ok/error/skipped, прежние "
        "ключи, без category/retryable/usage/...); модельно-видимый канал "
        "не менялся",
    ),
    "MCA_TOOL_DELIVERY_GUARD_ENABLED": (
        True,
        "без новой деривации idempotency-key/маркировки delivery_unknown из "
        "контура инструментов; mca-22/mca_trace-гарды как есть",
    ),
    "MCA_COST_ACCOUNTING_ENABLED": (
        True,
        "без новых точек записи расходов (embeddings) и usage_json-"
        "детализации; существующая аналитика как есть",
    ),
    # ── mca-11 (ADR-1028-13 D7): K4 блоков C/D + K5 (денежные лимиты) ──────
    "MCA_TOOL_CHAIN_STAGES_ENABLED": (
        True,
        "без стадийных событий `tools.chain` v2 (execute/deliver/account); "
        "реестр честно disabled/not_run (стадии не эмитятся)",
    ),
    "MCA_MONEY_LIMITS_ENABLED": (
        False,
        "денежные лимиты отключены — поведение 2.58.56 байт-в-байт "
        "(feature-гейт, не kill-switch: OFF по owner §20.2)",
    ),
    # ── mca-10a (ADR-1028-14 D11): K1–K4 RandomSource (env-only, default ON) ─
    "MCA_RANDOM_SOURCE_ENABLED": (
        True,
        "OFF → бит-в-бит 2.58.57: dream = default_source, ANU/refill/"
        "journal/витрина не активны (таблицы v27 инертны)",
    ),
    "MCA_RANDOM_QUANTUM_ENABLED": (
        True,
        "OFF → ANU-запросов/активации нет; при K1 ON effective=pseudorandom "
        "с причиной disabled; квота не расходуется",
    ),
    "MCA_RANDOM_REFILL_ENABLED": (
        True,
        "OFF → фоновый refill не запускается (запас только расходуется)",
    ),
    "MCA_RANDOM_EXPLORATION_ENABLED": (
        True,
        "OFF → политика возвращает primary; probability-draw нет "
        "(причина disabled)",
    ),
    # ── mca-10b (ADR-1028-17 D13, санкция spec §13.3): ровно один новый
    # kill-switch фичи (72→73); per-purpose аварийное отключение — каталог
    # `random.uses.*` (env-дубликатов нет); OFF = бит-в-бит 2.58.60.
    "MCA_RANDOM_USES_ENABLED": (
        True,
        "OFF → применения случайности (10b) не выполняются: пул/choose не "
        "строятся, фоновый hook молчит; 10a/сон/Decision как в 2.58.60 "
        "(честный disabled/not_run)",
    ),
    # ── mca-16 (ADR-1028-15 D11): K1–K4 банка опыта (env-only, default ON) ──
    "MCA_EXPERIENCE_LESSONS_ENABLED": (
        True,
        "OFF → бит-в-бит 2.58.58: нет записей/чтений/блока/событий/job; "
        "v28-таблицы инертны",
    ),
    "MCA_EXPERIENCE_FEEDBACK_ENABLED": (
        True,
        "OFF → feedback-контур (кроме technical-исходов) не пишется/"
        "не читается; injection-поверхность закрыта",
    ),
    "MCA_EXPERIENCE_REVIEW_ENABLED": (
        True,
        "OFF → review-job не запускается: propose/validate/activate/recheck "
        "не выполняются, статусы заморожены",
    ),
    "MCA_EXPERIENCE_CONTEXT_ENABLED": (
        True,
        "OFF → уроки не отбираются/не включаются/не применяются "
        "(bundle/context_version = 2.58.58); сбор опыта может продолжаться",
    ),
    # ── mca-09 (ADR-1028-16 D10): K1–K4 Intent/инициативы (env-only, ON) ────
    "MCA_INTENTS_ENABLED": (
        True,
        "OFF → бит-в-бит 2.58.59: v29 не читается/не пишется, heartbeat-джоб "
        "не регистрируется, кандидатов/событий нет, nostalgia legacy",
    ),
    "MCA_INTENT_HEARTBEAT_ENABLED": (
        True,
        "OFF → due-тик не работает; создание/закрытие намерений возможно, "
        "due-кандидатов нет",
    ),
    "MCA_INTENT_DECISION_ENABLED": (
        True,
        "OFF → инициативные решения/делегирование nostalgia не выполняются "
        "(nostalgia legacy); recheck-путь инертен",
    ),
    "MCA_SEND_RECHECK_ENABLED": (
        True,
        "OFF → новый recheck-слой не выполняется (документированное "
        "подмножество: существующие гейты остаются)",
    ),
    # ── mca-18 (ADR-1028-18 §8.3, санкция T-5074): ровно 3 kill-switch фичи
    # (73→76); env-only, default ON, OFF = бит-в-бит 2.58.61. K1 — мастер
    # (snapshot/resolve/frame/сборка; legacy-путь `build_persona_prompt_block`
    # сохраняется); K2/K3 — собственные оси (lifecycle черт / legacy-разбор),
    # v31-объекты инертны по своей оси.
    "MCA_SELF_MODEL_ENABLED": (
        True,
        "OFF → бит-в-бит 2.58.61: snapshot/resolve/frame/сборка не "
        "выполняются, промпт собирает legacy `build_persona_prompt_block`; "
        "v31 не читается/не пишется SelfModel-контуром",
    ),
    "MCA_TRAIT_RULES_ENABLED": (
        True,
        "OFF → lifecycle TraitObservation/BehaviorRule + анти-самоусиление + "
        "гарды не выполняются; v31-таблицы черт инертны (SelfModel-статусы "
        "честные disabled/not_run)",
    ),
    "MCA_LEGACY_TRAITS_MIGRATION_ENABLED": (
        True,
        "OFF → фоновый идемпотентный разбор `persona_traits` не запускается "
        "(лента/persona_traits не меняются)",
    ),
    # ── mca-19 (ADR-1028-19 §8.3/D13, санкция T-5099): ровно 4 kill-switch
    # фичи (76→80); env-only, default ON, OFF = бит-в-бит 2.58.62. K1 —
    # мастер (весь модуль: intake-реестр/анализ/чтение effective-статуса);
    # K2 — автоочередь новых изображений; K3 — архивный backfill; K4 — tool
    # recognize_image. Каталоговый тумблер владельца — отдельно
    # (flags.vision_enabled); OFF любого рубильника = новых vision-вызовов
    # нет, сохранённые разборы читаются офлайн.
    "MCA_VISION_ENABLED": (
        True,
        "OFF → бит-в-бит 2.58.62: модуль распознавания изображений не "
        "существует (intake-активы не пишутся, анализы/чтение "
        "effective-статуса недоступны)",
    ),
    "MCA_VISION_AUTO_ENABLED": (
        True,
        "OFF → автоочередь новых изображений не запускается (инертен при "
        "мастере OFF); ручной/tool путь не гейтится этим рубильником",
    ),
    "MCA_VISION_BACKFILL_ENABLED": (
        True,
        "OFF → архивный backfill старых изображений не запускается "
        "(инертен при мастере OFF)",
    ),
    "MCA_VISION_TOOL_ENABLED": (
        True,
        "OFF → tool recognize_image скрыт из набора; серверная проверка OFF "
        "для устаревших вызовов остаётся (defence in depth; инертен при "
        "мастере OFF)",
    ),
    # ── mca-20 (ADR-1028-20 §8.3/D13, санкция T-5131): ровно 3 kill-switch
    # фичи (80→83); env-only, default ON, OFF = бит-в-бит d298f1f/2.58.63.
    # K1 — master (ON-путь envelope-пайплайна; OFF → легаси-путь хендлера,
    # включая легаси-кеш-слаг `factcheck`); K2 — tool `fact_check`; K3 — кеш
    # готовых вердиктов (кеш поиска/загрузок не трогается).
    "MCA_TEMPORAL_FACTCHECK_ENABLED": (
        True,
        "OFF → бит-в-бит d298f1f/2.58.63: ON-путь envelope-пайплайна не "
        "выполняется (легаси-путь хендлера, включая легаси-кеш-слаг "
        "`factcheck`; v33 не читается/не пишется temporal-контуром)",
    ),
    "MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED": (
        True,
        "OFF → tool fact_check скрыт из набора; серверная проверка OFF для "
        "устаревших вызовов остаётся (defence in depth; инертен при мастере "
        "OFF)",
    ),
    "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED": (
        True,
        "OFF → готовые вердикты всегда вычисляются без кеширования (reason "
        "temporal_cache_disabled); кеш поиска/загрузок (slug "
        "search/web/youtube) не затрагивается; инертен при мастере OFF",
    ),
    # ── mca-12 (ADR-1028-21 §8.3/D13, санкция T-5154): ровно 2 kill-switch
    # фичи (83→85); env-only, default ON, OFF = паритет по своей оси.
    # K1 — мастер витринного контура (блок «Истории чата» на «Статусе» +
    # read-API `/api/stories/summary|/feed|/api/stories|/api/stories/{id}` +
    # витрины T-5169); K2 — мутационный контур (POST /api/stories/{id}/action).
    # Гейты НЕЗАВИСИМЫ по осям (прецедент mca-07); `MCA_EPISODES_ENABLED` /
    # `MCA_EVENT_CONTRACT_ENABLED` / `MCA_PROVENANCE_ENABLED` уважаются,
    # не дублируются.
    "MCA_STORIES_VITRINA_ENABLED": (
        True,
        "OFF → блок «Истории чата» скрыт, read-API отвечает честным "
        "disabled-состоянием (не 404-заглушка); существующие виджеты не "
        "затронуты (паритет по своей оси)",
    ),
    "MCA_STORIES_MANAGE_ENABLED": (
        True,
        "OFF → только просмотр; POST action отклоняется честным disabled "
        "(409); сам фасад mca-05 не выключается (его жизненный цикл — "
        "MCA_EPISODES_ENABLED)",
    ),
}


def tx_ownership_enabled() -> bool:
    """`MCA_TX_OWNERSHIP_ENABLED` (default ON).

    ON → транзакцией владеет задача, получившая lock; rollback/очистка
    выполняются под lock; отмена ожидающего не меняет чужую транзакцию.
    OFF → прежний `write_transaction` (паритет baseline 7165ff7)."""
    return bool(getattr(settings, "MCA_TX_OWNERSHIP_ENABLED", True))


def task_supervisor_enabled() -> bool:
    """`MCA_TASK_SUPERVISOR_ENABLED` (default ON).

    ON → активны примитивы TaskSupervisor (coalescing/singleflight,
    bounded-очереди; durable `task_jobs` — v14). OFF → прозрачный
    pass-through без коалесинга/ограничения."""
    return bool(getattr(settings, "MCA_TASK_SUPERVISOR_ENABLED", True))


def schema_migrations_enabled() -> bool:
    """`MCA_SCHEMA_MIGRATIONS_ENABLED` (default ON).

    ON → реестр шагов + книга `schema_migrations` + backup/read-back.
    OFF → hardcoded legacy-последовательность `_migrate_*` (паритет baseline)."""
    return bool(getattr(settings, "MCA_SCHEMA_MIGRATIONS_ENABLED", True))


def event_contract_enabled() -> bool:
    """`MCA_EVENT_CONTRACT_ENABLED` (default ON).

    ON → контракт §17.1: `start`+терминальный `outcome`, словарь `reason_code`,
    ошибки/агрегация. OFF → события ровно как в baseline (без start/outcome)."""
    return bool(getattr(settings, "MCA_EVENT_CONTRACT_ENABLED", True))


def telemetry_store_enabled() -> bool:
    """`MCA_TELEMETRY_STORE_ENABLED` (default ON).

    ON → терминальные события durable-персистятся в `mca_events` (v15).
    OFF → только структурный лог, без durable-записи (паритет baseline)."""
    return bool(getattr(settings, "MCA_TELEMETRY_STORE_ENABLED", True))


def message_identity_enabled() -> bool:
    """`MCA_MESSAGE_IDENTITY_ENABLED` (default ON, ADR-1027-4 D9).

    ON → producers пишут каноническую идентичность `(chat_id, tg_message_id)`,
    source records и поля времени/ролей; OFF → legacy-путь
    (`save_smart_message`), паритет baseline 7165ff7."""
    return bool(getattr(settings, "MCA_MESSAGE_IDENTITY_ENABLED", True))


def message_revision_tracking_enabled() -> bool:
    """`MCA_MESSAGE_REVISION_TRACKING_ENABLED` (default ON, ADR-1027-4 D9).

    ON → правки человека создают версию (`message_revisions`) и обновляют
    актуальную; OFF → редакции без версионирования (текущее поведение)."""
    return bool(getattr(settings, "MCA_MESSAGE_REVISION_TRACKING_ENABLED",
                        True))


def safe_fetch_enabled() -> bool:
    """`MCA_SAFE_FETCH_ENABLED` (default ON, ADR-1027-5 D12).

    ON → внешние загрузки идут через SafeFetcher (SSRF/redirect/лимиты/
    peer-проверка). OFF → legacy-путь загрузки (паритет baseline 7165ff7)."""
    return bool(getattr(settings, "MCA_SAFE_FETCH_ENABLED", True))


def egress_guard_enabled() -> bool:
    """`MCA_EGRESS_GUARD_ENABLED` (default ON, ADR-1027-5 D12).

    ON → in-process loopback egress-guard для медиа-подпроцессов/yt-dlp/
    transcript-api. OFF → legacy без egress-обвязки (паритет baseline)."""
    return bool(getattr(settings, "MCA_EGRESS_GUARD_ENABLED", True))


def provenance_enabled() -> bool:
    """`MCA_PROVENANCE_ENABLED` (default ON, ADR-1027-6 D11).

    ON → создаются/читаются типизированные SourceRef/EvidenceLink/статусы.
    OFF → legacy-путь (`source_ids`/`tg_message_id` как есть; новые записи/
    связи не создаются; паритет baseline)."""
    return bool(getattr(settings, "MCA_PROVENANCE_ENABLED", True))


def fact_attribution_enabled() -> bool:
    """`MCA_FACT_ATTRIBUTION_ENABLED` (default ON, ADR-1027-6 D11).

    Инертен при `MCA_PROVENANCE_ENABLED=OFF`: без provenance субъект-атрибуция
    не создаётся, поэтому effective = OFF. ON → субъект-атрибуция личных
    фактов + subject-scope читателей + сохранение Layer B `person_facts`.
    OFF → legacy-атрибуция (`target=asker`, name-scope; паритет baseline)."""
    if not provenance_enabled():
        return False
    return bool(getattr(settings, "MCA_FACT_ATTRIBUTION_ENABLED", True))


def evidence_reconstruction_enabled() -> bool:
    """`MCA_EVIDENCE_RECONSTRUCTION_ENABLED` (default ON, ADR-1027-6 D11).

    Инертен при `MCA_PROVENANCE_ENABLED=OFF`. ON → восстановление старых
    записей (read-time/backfill-recovery) разрешено; OFF → восстановление не
    запускается (прямо сохранённое происхождение по-прежнему фиксируется)."""
    if not provenance_enabled():
        return False
    return bool(getattr(settings, "MCA_EVIDENCE_RECONSTRUCTION_ENABLED", True))


def retrieval_context_enabled() -> bool:
    """`MCA_RETRIEVAL_CONTEXT_ENABLED` (default ON, ADR-1027-7 D12).

    ON → единый retrieval-контракт (комбинация каналов + эпизоды-первыми для
    истории) и embedding-identity-политика (fingerprint/generation). OFF →
    legacy-вызовы каналов и прежний `sha256(casefold+strip)` + dim-проверка
    (паритет baseline)."""
    return bool(getattr(settings, "MCA_RETRIEVAL_CONTEXT_ENABLED", True))


def evidence_bundle_enabled() -> bool:
    """`MCA_EVIDENCE_BUNDLE_ENABLED` (default ON, ADR-1027-7 D5/D6).

    ON → контекст собирается в один in-memory EvidenceBundle, проходящий все
    стадии. OFF → legacy-сборка контекста (паритет baseline)."""
    return bool(getattr(settings, "MCA_EVIDENCE_BUNDLE_ENABLED", True))


def adaptive_context_budget_enabled() -> bool:
    """`MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` (default ON, ADR-1027-7 D7).

    ON → полный учёт payload (system/developer/personality, tools, tool
    results, output reserve, overhead) + консервативная оценка + protected
    spans + pre-flight. OFF → прежний `_apply_context_budget`."""
    return bool(getattr(settings, "MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED", True))


def typed_reranker_enabled() -> bool:
    """`MCA_TYPED_RERANKER_ENABLED` (default ON, ADR-1027-7 D3).

    ON → reranker возвращает типизированный список ID; валидный пустой список
    ≠ все кандидаты; `invalid`/`timeout`/`error` → отдельный статус +
    детерминированный bounded fallback. OFF → прежнее поведение."""
    return bool(getattr(settings, "MCA_TYPED_RERANKER_ENABLED", True))


def summary_singleflight_enabled() -> bool:
    """`MCA_SUMMARY_SINGLEFLIGHT_ENABLED` (default ON, ADR-1027-7 D8).

    ON → singleflight/coalescing + high-watermark/CAS сводок (поздний старый
    запрос не перезаписывает новую версию). OFF → прежний fire-and-forget."""
    return bool(getattr(settings, "MCA_SUMMARY_SINGLEFLIGHT_ENABLED", True))


def context_answer_cache_enabled() -> bool:
    """`MCA_CONTEXT_ANSWER_CACHE_ENABLED` (default ON, ADR-1027-7 D9).

    ON → MCA-07 context-keyed политика: legacy text-replay по одному
    нормализованному query/chat/user для контекстных ответов отключён;
    update-дедуп по `(chat_id, tg_message_id)` сохранён. OFF → прежний
    ответный кеш (паритет baseline)."""
    return bool(getattr(settings, "MCA_CONTEXT_ANSWER_CACHE_ENABLED", True))


# ── mca-17a (ADR-1027-8 D6/D7/D12): ядро наблюдаемости ─────────────────────
# Мастер `MCA_OBSERVABILITY_ENABLED`: OFF → паритет baseline целиком. Под-гейты
# инертны при master OFF (кроме fault-injection — он вне product-контура).

def observability_enabled() -> bool:
    """`MCA_OBSERVABILITY_ENABLED` (мастер, default ON, ADR-1027-8 D12)."""
    return bool(getattr(settings, "MCA_OBSERVABILITY_ENABLED", True))


def process_registry_enabled() -> bool:
    """`MCA_PROCESS_REGISTRY_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_PROCESS_REGISTRY_ENABLED", True))


def trace_span_enabled() -> bool:
    """`MCA_TRACE_SPAN_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_TRACE_SPAN_ENABLED", True))


def job_lifecycle_enabled() -> bool:
    """`MCA_JOB_LIFECYCLE_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_JOB_LIFECYCLE_ENABLED", True))


def heartbeat_watchdog_enabled() -> bool:
    """`MCA_HEARTBEAT_WATCHDOG_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_HEARTBEAT_WATCHDOG_ENABLED", True))


def incidents_enabled() -> bool:
    """`MCA_INCIDENTS_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_INCIDENTS_ENABLED", True))


def incident_push_enabled() -> bool:
    """`MCA_INCIDENT_PUSH_ENABLED` (default ON; инертен при master/incidents)."""
    if not observability_enabled() or not incidents_enabled():
        return False
    return bool(getattr(settings, "MCA_INCIDENT_PUSH_ENABLED", True))


def telemetry_spool_enabled() -> bool:
    """`MCA_TELEMETRY_SPOOL_ENABLED` (default ON; инертен при master OFF)."""
    if not observability_enabled():
        return False
    return bool(getattr(settings, "MCA_TELEMETRY_SPOOL_ENABLED", True))


# ── mca-04b (ADR-1027-9 D13): dossier rebuild ───────────────────────────────
# Мастер + под-гейты; `MCA_DOSSIER_*` инертны при OFF нижележащих.

def dossier_rebuild_enabled() -> bool:
    """`MCA_DOSSIER_REBUILD_ENABLED` (мастер, default ON).

    ON → единый контракт full rebuild (keyset/staging/честная финализация);
    OFF → legacy `run_dossier_rebuild` как сейчас (паритет baseline)."""
    return bool(getattr(settings, "MCA_DOSSIER_REBUILD_ENABLED", True))


def dossier_background_pass_enabled() -> bool:
    """`MCA_DOSSIER_BACKGROUND_PASS_ENABLED` (default ON; инертен при master)."""
    if not dossier_rebuild_enabled():
        return False
    return bool(getattr(settings, "MCA_DOSSIER_BACKGROUND_PASS_ENABLED", True))


def dossier_read_reconstruction_enabled() -> bool:
    """`MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED` (default ON).

    Инертен при `MCA_EVIDENCE_RECONSTRUCTION_ENABLED=OFF` (§98 — не
    дублируется): без нижележащего гейта восстановление невозможно."""
    if not evidence_reconstruction_enabled():
        return False
    return bool(getattr(settings, "MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED",
                        True))


def dossier_reclassify_enabled() -> bool:
    """`MCA_DOSSIER_RECLASSIFY_ENABLED` (default ON; инертен при master)."""
    if not dossier_rebuild_enabled():
        return False
    return bool(getattr(settings, "MCA_DOSSIER_RECLASSIFY_ENABLED", True))


def dossier_staging_activation_enabled() -> bool:
    """`MCA_DOSSIER_STAGING_ACTIVATION_ENABLED` (default ON; инертен при master).

    ON → staging/generation + атомарная активация; OFF → прямая запись
    существующими writer'ами (паритет baseline-записи)."""
    if not dossier_rebuild_enabled():
        return False
    return bool(getattr(settings, "MCA_DOSSIER_STAGING_ACTIVATION_ENABLED",
                        True))


def embedding_generation_activation_enabled() -> bool:
    """`MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED` (default ON).

    ON → операция активации vec-поколения (N-MCA07-1, REUSE v18);
    OFF → gate mca-07 FTS-only как сейчас."""
    return bool(getattr(settings, "MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED",
                        True))


def dossier_namespace_fingerprint_v2_enabled() -> bool:
    """`MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED` (default ON, L-MCA03-8).

    ON → namespace-отпечаток импорта версионируется (`v2` в отпечатке,
    content-fingerprint); OFF → прежний `import:<tag>:<digest>`."""
    return bool(getattr(
        settings, "MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED", True))


# ── mca-05 (ADR-1027-12 D13): episodes/stories ──────────────────────────────
# Мастер + под-гейты; под-гейты инертны при master OFF.

def episodes_enabled() -> bool:
    """`MCA_EPISODES_ENABLED` (мастер, default ON, ADR-1027-12 D13).

    ON → модель/пайплайн эпизодов/историй активны; OFF → точный паритет
    baseline (`lore_stories`/компилятор/mca-07 канал работают как сегодня)."""
    return bool(getattr(settings, "MCA_EPISODES_ENABLED", True))


def episodes_backfill_enabled() -> bool:
    """`MCA_EPISODES_BACKFILL_ENABLED` (default ON; инертен при master OFF)."""
    if not episodes_enabled():
        return False
    return bool(getattr(settings, "MCA_EPISODES_BACKFILL_ENABLED", True))


def episodes_continuation_enabled() -> bool:
    """`MCA_EPISODES_CONTINUATION_ENABLED` (default ON; инертен при master)."""
    if not episodes_enabled():
        return False
    return bool(getattr(settings, "MCA_EPISODES_CONTINUATION_ENABLED", True))


def episodes_compiler_facade_enabled() -> bool:
    """`MCA_EPISODES_COMPILER_FACADE_ENABLED` (default ON; инертен при master).

    ON → компилятор и mca-07 episode-канал читают новый store через фасад
    (legacy `lore_stories` сохраняются); OFF → как сегодня (legacy-путь)."""
    if not episodes_enabled():
        return False
    return bool(getattr(settings, "MCA_EPISODES_COMPILER_FACADE_ENABLED", True))


# ── mca-22 (ADR-1028-6 D10): FINAL INTEGRATION — 4 рубильника фичи ─────────
# Инертности: canonical OFF ⇒ quote/claim/attribution-ветки недостижимы;
# ledger OFF ⇒ correction не может резолвить бот-цитаты через priority 5
# (fallback 6/7); observability OFF ⇒ события только structural log.

def canonical_attribution_enabled() -> bool:
    """`MCA_CANONICAL_ATTRIBUTION_ENABLED` (мастер фичи, default ON).

    ON → canonical envelope/read projection, quote resolver, claim envelope,
    speaker≠subject, producer-validator, GraphRAG provenance enforcement и
    retrieval attribution активны. OFF → точный паритет baseline (существующие
    SELECT/записи; роль-колонки не используются)."""
    return bool(getattr(settings, "MCA_CANONICAL_ATTRIBUTION_ENABLED", True))


def bot_output_ledger_enabled() -> bool:
    """`MCA_BOT_OUTPUT_LEDGER_ENABLED` (default ON; инертен при canonical OFF
    для read-веток quote-resolver; write-ветка самостоятельна).

    ON → durable ledger `mca_bot_outputs` пишется/читается. OFF → `bot_replies`
    как сегодня; quote-priority 5 недоступна (лестница падает на 6/7)."""
    return bool(getattr(settings, "MCA_BOT_OUTPUT_LEDGER_ENABLED", True))


def correction_revalidation_enabled() -> bool:
    """`MCA_CORRECTION_REVALIDATION_ENABLED` (default ON; инертен при
    canonical OFF — correction строится над существующей provenance-схемой и
    envelope-контрактом)."""
    if not canonical_attribution_enabled():
        return False
    return bool(getattr(settings, "MCA_CORRECTION_REVALIDATION_ENABLED", True))


def response_freshness_guard_enabled() -> bool:
    """`MCA_RESPONSE_FRESHNESS_GUARD_ENABLED` (default ON).

    ON → update-dedup/no-replay/duplicate guard/freshness retry/lineage-
    события активны. OFF → текущее поведение (legacy text-dedup — под своей
    политикой `MCA_CONTEXT_ANSWER_CACHE_ENABLED`)."""
    return bool(getattr(settings, "MCA_RESPONSE_FRESHNESS_GUARD_ENABLED", True))


def episodes_batch_max_messages() -> int:
    """`MCA_EPISODES_BATCH_MAX_MESSAGES` (env-only, default 500).

    Размер ПОРЦИИ обработки в сообщениях (не токен-бюджет, ADR-1027-12 D6
    по прецеденту ADR-1027-9 D14); значение <1 → 500."""
    try:
        return max(1, int(getattr(settings, "MCA_EPISODES_BATCH_MAX_MESSAGES",
                                  500)))
    except Exception:      # pragma: no cover - защитная ветка
        return 500


def episodes_direct_priority_enabled() -> bool:
    """`MCA_EPISODES_DIRECT_PRIORITY_ENABLED` (env-only, default ON).

    ON → фоновая сборка эпизодов не блокирует direct-flow (приоритет прямых
    ответов)."""
    return bool(getattr(settings, "MCA_EPISODES_DIRECT_PRIORITY_ENABLED", True))


def dossier_direct_priority_enabled() -> bool:
    """`MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` (env-only, default ON).

    ON → фоновая пересборка не блокирует direct-flow (приоритет прямых
    ответов)."""
    return bool(getattr(settings, "MCA_DOSSIER_DIRECT_PRIORITY_ENABLED", True))


def dossier_batch_max_messages() -> int:
    """`MCA_DOSSIER_BATCH_MAX_MESSAGES` (env-only, default 500).

    Размер ПОРЦИИ обработки в сообщениях (не токен-бюджет, ADR D14);
    значение <1 → 500."""
    try:
        return max(1, int(getattr(settings, "MCA_DOSSIER_BATCH_MAX_MESSAGES",
                                  500)))
    except Exception:      # pragma: no cover - защитная ветка
        return 500


def fault_injection_enabled() -> bool:
    """`MCA_FAULT_INJECTION_ENABLED` (default **OFF**; dev/test-only).

    Не product-функция и не виджет; вне effective-state §20.2 (§5.5)."""
    return bool(getattr(settings, "MCA_FAULT_INJECTION_ENABLED", False))


def _int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(getattr(settings, name, default)))
    except Exception:      # pragma: no cover - защитная ветка
        return default


def job_heartbeat_seconds() -> int:
    """`MCA_JOB_HEARTBEAT_SECONDS` (env-only, default 15)."""
    return _int_setting("MCA_JOB_HEARTBEAT_SECONDS", 15)


def job_stale_seconds() -> int:
    """`MCA_JOB_STALE_SECONDS` (env-only, default 60)."""
    return _int_setting("MCA_JOB_STALE_SECONDS", 60)


def incident_push_interval_seconds() -> int:
    """`MCA_INCIDENT_PUSH_INTERVAL_SECONDS` (env-only, default 10; ≤10 цель)."""
    return _int_setting("MCA_INCIDENT_PUSH_INTERVAL_SECONDS", 10)


def telemetry_spool_max_events() -> int:
    """`MCA_TELEMETRY_SPOOL_MAX_EVENTS` (env-only, default 2000)."""
    return _int_setting("MCA_TELEMETRY_SPOOL_MAX_EVENTS", 2000)


_PROGRESS_STALL_BY_TYPE = {
    "llm": "MCA_PROGRESS_STALL_LLM_SECONDS",
    "video": "MCA_PROGRESS_STALL_VIDEO_SECONDS",
    "archive": "MCA_PROGRESS_STALL_ARCHIVE_SECONDS",
}


def progress_stall_seconds(stage_type: str | None = None) -> int:
    """Порог progress-stall по типу стадии (`MCA_PROGRESS_STALL_<TYPE>_SECONDS`).

    Тип по умолчанию — общий (`MCA_PROGRESS_STALL_DEFAULT_SECONDS`, 600).
    Законная длительная транскрибация/архив не объявляется упавшей по общему
    таймеру stale (ADR-1027-8 D7)."""
    key = _PROGRESS_STALL_BY_TYPE.get(str(stage_type or "").lower())
    if key is not None:
        return _int_setting(key, _int_setting(
            "MCA_PROGRESS_STALL_DEFAULT_SECONDS", 600))
    return _int_setting("MCA_PROGRESS_STALL_DEFAULT_SECONDS", 600)


def detailed_log_retention_days() -> int:
    """`MCA_DETAILED_LOG_RETENTION_DAYS` (env-only, default 14).

    Ретенция подробных диагностических строк (структурный лог/ring). Никогда
    не бросает; значение <1 → 14."""
    try:
        return max(1, int(getattr(settings, "MCA_DETAILED_LOG_RETENTION_DAYS",
                                  14)))
    except Exception:      # pragma: no cover - защитная ветка
        return 14


def terminal_event_retention_days() -> int:
    """`MCA_TERMINAL_EVENT_RETENTION_DAYS` (env-only, default 90).

    Ретенция терминальных событий `mca_events`. Никогда не бросает;
    значение <1 → 90."""
    try:
        return max(1, int(getattr(settings, "MCA_TERMINAL_EVENT_RETENTION_DAYS",
                                  90)))
    except Exception:      # pragma: no cover - защитная ветка
        return 90


# ── mca-06 (ADR-1028-9): kill-switch'и + единый gate-resolver сна ──────────
# Один resolver на 4 потребителя (scheduler / ручной запуск / worker / UI);
# 8 различимых причин; фиксированный порядок §3.2; resolver информационный —
# нового human gate не создаёт. Второй резолвер запрещён.

def dream_gate_resolver_enabled() -> bool:
    """`MCA_DREAM_GATE_RESOLVER_ENABLED` (env-only, default ON; §3)."""
    return bool(getattr(settings, "MCA_DREAM_GATE_RESOLVER_ENABLED", True))


def dream_historical_profile_enabled() -> bool:
    """`MCA_DREAM_HISTORICAL_PROFILE_ENABLED` (env-only, default ON; §4)."""
    return bool(getattr(settings, "MCA_DREAM_HISTORICAL_PROFILE_ENABLED", True))


def dream_evidence_typing_enabled() -> bool:
    """`MCA_DREAM_EVIDENCE_TYPING_ENABLED` (env-only, default ON; §5/§8.1)."""
    return bool(getattr(settings, "MCA_DREAM_EVIDENCE_TYPING_ENABLED", True))


def dream_quotas_split_enabled() -> bool:
    """`MCA_DREAM_QUOTAS_SPLIT_ENABLED` (env-only, default ON; §6)."""
    return bool(getattr(settings, "MCA_DREAM_QUOTAS_SPLIT_ENABLED", True))


def dream_run_reports_enabled() -> bool:
    """`MCA_DREAM_RUN_REPORTS_ENABLED` (env-only, default ON; §7.2)."""
    return bool(getattr(settings, "MCA_DREAM_RUN_REPORTS_ENABLED", True))


def dream_revision_queue_enabled() -> bool:
    """`MCA_DREAM_REVISION_QUEUE_ENABLED` (env-only, default ON; §8.4)."""
    return bool(getattr(settings, "MCA_DREAM_REVISION_QUEUE_ENABLED", True))


def dream_revision_queue_cap() -> int:
    """Cap очереди пересмотра за цикл (env-only, default 20; §8.4)."""
    return _int_setting_min("MCA_DREAM_REVISION_QUEUE_CAP", 20, 1)


def dream_random_explore_enabled() -> bool:
    """`MCA_DREAM_RANDOM_EXPLORE_ENABLED` (env-only, default ON; §8.7)."""
    return bool(getattr(settings, "MCA_DREAM_RANDOM_EXPLORE_ENABLED", True))


# ── mca-08 (ADR-1028-11 D10) блоки A+B: K1/K2 ───────────────────────────────
def character_layers_enabled() -> bool:
    """`MCA_CHARACTER_LAYERS_ENABLED` (env-only, default ON; D1/D2).

    ON → read-контекст слоёв (`resolve_character_context`) + `<Character_Rules>`
    + `character_block` у verbalizer. OFF → точный паритет 2.58.54."""
    return bool(getattr(settings, "MCA_CHARACTER_LAYERS_ENABLED", True))


def character_speech_enabled() -> bool:
    """`MCA_CHARACTER_SPEECH_ENABLED` (env-only, default ON; D6/D7).

    ON → `SpeechUnderstanding`/`<Speech_Understanding>`/clarify в ответном
    пути. OFF → точный паритет 2.58.54."""
    return bool(getattr(settings, "MCA_CHARACTER_SPEECH_ENABLED", True))


# ── mca-08 (ADR-1028-11 D10) блоки C+D: K3/K4 + env-only TTL ────────────────
def style_scope_enabled() -> bool:
    """`MCA_STYLE_SCOPE_ENABLED` (env-only, default ON; D3–D5).

    ON → ingestion/права/резолв scoped-просьб + `<Style_Requests>` +
    скрытая команда `/style`. OFF → точный паритет 2.58.54 (таблица
    `mca_style_requests` не читается/не пишется; команда неактивна)."""
    return bool(getattr(settings, "MCA_STYLE_SCOPE_ENABLED", True))


def postprocess_form_guard_enabled() -> bool:
    """`MCA_POSTPROCESS_FORM_GUARD_ENABLED` (env-only, default ON; D8).

    ON → форма G1–G3 + bounded повтор + fallback у `verbalize_validated`
    (только при переданном `form_contract`). OFF → как 2.58.54: новые
    параметры игнорируются, stats без новых ключей."""
    return bool(getattr(settings, "MCA_POSTPROCESS_FORM_GUARD_ENABLED", True))


# ── mca-15 (ADR-1028-12 D8): K1/K2/K3 + env-only лимиты ─────────────────────
def chat_statistics_enabled() -> bool:
    """`MCA_CHAT_STATISTICS_ENABLED` (env-only, default ON; D8/K1).

    ON → stats-режим/measurement + FIX измерительных путей. OFF → точный
    паритет 2.58.55 (ярлык «Найдено N упоминаний», голый `total_mentions`,
    старый truncation-контракт)."""
    return bool(getattr(settings, "MCA_CHAT_STATISTICS_ENABLED", True))


def numeric_claim_guard_enabled() -> bool:
    """`MCA_NUMERIC_CLAIM_GUARD_ENABLED` (env-only, default ON; D8/K2).

    ON → numeric-контракт `verbalize_validated` + финальная сборка direct
    (блоки C/D). OFF → точный паритет 2.58.55 (новые параметры
    игнорируются)."""
    return bool(getattr(settings, "MCA_NUMERIC_CLAIM_GUARD_ENABLED", True))


def stats_intent_enabled() -> bool:
    """`MCA_STATS_INTENT_ENABLED` (env-only, default ON; D8/K3).

    ON → классификатор `social_banter`/`historical_evidence`/
    `chat_statistics`/`mixed` + stats-хинт + reason-коды цели. OFF →
    intent-поведение как 2.58.55 (классификатор не вызывается)."""
    return bool(getattr(settings, "MCA_STATS_INTENT_ENABLED", True))


# ── mca-11 (ADR-1028-13 D7): K1/K2/K3 ToolResult/доставки/учёта ─────────────
def tool_result_enabled() -> bool:
    """`MCA_TOOL_RESULT_ENABLED` (env-only, default ON; K1).

    ON → канонический ToolResult-envelope (7 статусов + аддитивные поля).
    OFF → legacy-путь 2.58.56 байт-в-байт (ok/error/skipped)."""
    return bool(getattr(settings, "MCA_TOOL_RESULT_ENABLED", True))


def tool_delivery_guard_enabled() -> bool:
    """`MCA_TOOL_DELIVERY_GUARD_ENABLED` (env-only, default ON; K2).

    ON → idempotency key side effects + маркировка `delivery_unknown` из
    контура инструментов. OFF → без новой деривации ключа/маркировки
    (mca-22/mca_trace-гарды не меняются)."""
    return bool(getattr(settings, "MCA_TOOL_DELIVERY_GUARD_ENABLED", True))


def cost_accounting_enabled() -> bool:
    """`MCA_COST_ACCOUNTING_ENABLED` (env-only, default ON; K3).

    ON → новые точки записи расходов (embeddings) + usage-детализация.
    OFF → без новых точек записи/`usage_json`; существующая аналитика как
    есть."""
    return bool(getattr(settings, "MCA_COST_ACCOUNTING_ENABLED", True))


# ── mca-11 (ADR-1028-13 D6/D7): K4 стадии tools.chain + K5 денежные лимиты ──
def tool_chain_stages_enabled() -> bool:
    """`MCA_TOOL_CHAIN_STAGES_ENABLED` (env-only, default ON; K4).

    ON → стадийные события `tools.chain` v2 (execute/deliver/account,
    notable-only; R17-safe). OFF → стадийных событий нет; реестр отдаёт
    честный статус (disabled/not_run), а не implemented."""
    return bool(getattr(settings, "MCA_TOOL_CHAIN_STAGES_ENABLED", True))


def money_limits_enabled() -> bool:
    """`MCA_MONEY_LIMITS_ENABLED` (env-only, default **OFF**; K5).

    Feature-гейт нового механизма денежных лимитов (owner §20.2): OFF →
    поведение 2.58.56 байт-в-байт; ON → инертная семантика активируется
    (резерв/overshoot/reconcile; приоритет direct > autonomous >
    maintenance)."""
    return bool(getattr(settings, "MCA_MONEY_LIMITS_ENABLED", False))


# ── mca-10a (ADR-1028-14 D11): K1–K4 RandomSource + env-only лимиты ────────
def random_source_enabled() -> bool:
    """`MCA_RANDOM_SOURCE_ENABLED` (master, env-only, default ON; K1).

    ON → RandomSource-контур активен (ANU/запас/журнал/политика).
    OFF → бит-в-бит 2.58.57: dream = `default_source`, сеть/записи v27/
    события/витрина не активны."""
    return bool(getattr(settings, "MCA_RANDOM_SOURCE_ENABLED", True))


def random_quantum_enabled() -> bool:
    """`MCA_RANDOM_QUANTUM_ENABLED` (env-only, default ON; K2).

    ON → ANU-клиент/активация разрешены. OFF → ANU-запросов нет; при K1 ON
    effective=pseudorandom с причиной `disabled` (квота не расходуется)."""
    return bool(getattr(settings, "MCA_RANDOM_QUANTUM_ENABLED", True))


def random_refill_enabled() -> bool:
    """`MCA_RANDOM_REFILL_ENABLED` (env-only, default ON; K3).

    ON → фоновый singleflight-refill по low watermark. OFF → refill не
    запускается (запас только расходуется)."""
    return bool(getattr(settings, "MCA_RANDOM_REFILL_ENABLED", True))


def random_exploration_enabled() -> bool:
    """`MCA_RANDOM_EXPLORATION_ENABLED` (env-only, default ON; K4).

    ON → `ExplorationPolicy.choose` выполняет одну probability-проверку.
    OFF → политика возвращает primary без draw (причина `disabled`)."""
    return bool(getattr(settings, "MCA_RANDOM_EXPLORATION_ENABLED", True))


def random_uses_enabled() -> bool:
    """`MCA_RANDOM_USES_ENABLED` (env-only, default ON; mca-10b master).

    ON → применения случайности (10b, ADR-1028-17 D13) активны — каждое
    дополнительно гейтится каталогом `random.uses.*` (до каталога —
    `memory.random_uses_*` через read-path с дефолтом True) и существующими
    K1/K4 для probability-веток. OFF → вся 10b-поверхность не выполняется:
    бит-в-бит 2.58.60, честный `disabled`/`not_run`."""
    return bool(getattr(settings, "MCA_RANDOM_USES_ENABLED", True))


def experience_lessons_enabled() -> bool:
    """`MCA_EXPERIENCE_LESSONS_ENABLED` (env-only, default ON; K1 master).

    ON → банк опыта активен (эпизоды/feedback/уроки/применения).
    OFF → бит-в-бит 2.58.58: модуль инертен — ни записей, ни чтений, ни
    блока, ни job, ни событий; v28-таблицы не читаются."""
    return bool(getattr(settings, "MCA_EXPERIENCE_LESSONS_ENABLED", True))


def experience_feedback_enabled() -> bool:
    """`MCA_EXPERIENCE_FEEDBACK_ENABLED` (env-only, default ON; K2).

    ON → feedback-контур принимает все типизированные сигналы.
    OFF → принимаются только technical-исходы; остальные не пишутся и не
    читаются (injection-поверхность закрыта)."""
    return bool(getattr(settings, "MCA_EXPERIENCE_FEEDBACK_ENABLED", True))


def experience_review_enabled() -> bool:
    """`MCA_EXPERIENCE_REVIEW_ENABLED` (env-only, default ON; K3).

    ON → review-job/propose/validate/activate/recheck работают.
    OFF → переходы статусов не выполняются (статусы заморожены)."""
    return bool(getattr(settings, "MCA_EXPERIENCE_REVIEW_ENABLED", True))


def experience_context_enabled() -> bool:
    """`MCA_EXPERIENCE_CONTEXT_ENABLED` (env-only, default ON; K4).

    ON → отбор/включение/применение уроков в контексте.
    OFF → lessons не отбираются и не включаются (bundle = 2.58.58);
    сбор опыта может продолжаться."""
    return bool(getattr(settings, "MCA_EXPERIENCE_CONTEXT_ENABLED", True))


def experience_review_batch_max() -> int:
    """`MCA_EXPERIENCE_REVIEW_BATCH_MAX` (env-only, default 100; ≥1)."""
    return _int_setting_min("MCA_EXPERIENCE_REVIEW_BATCH_MAX", 100, 1)


def experience_episode_retention_days() -> int:
    """`MCA_EXPERIENCE_EPISODE_RETENTION_DAYS` (env-only, default 90; ≥1)."""
    return _int_setting_min("MCA_EXPERIENCE_EPISODE_RETENTION_DAYS", 90, 1)


def experience_feedback_retention_days() -> int:
    """`MCA_EXPERIENCE_FEEDBACK_RETENTION_DAYS` (env-only, default 180; ≥1)."""
    return _int_setting_min("MCA_EXPERIENCE_FEEDBACK_RETENTION_DAYS", 180, 1)


def lesson_application_retention_days() -> int:
    """`MCA_LESSON_APPLICATION_RETENTION_DAYS` (env-only, default 180; ≥1)."""
    return _int_setting_min("MCA_LESSON_APPLICATION_RETENTION_DAYS", 180, 1)


def lesson_block_max_items() -> int:
    """`MCA_LESSON_BLOCK_MAX_ITEMS` (env-only, default 5; ≥1)."""
    return _int_setting_min("MCA_LESSON_BLOCK_MAX_ITEMS", 5, 1)


def lesson_block_max_tokens() -> int:
    """`MCA_LESSON_BLOCK_MAX_TOKENS` (env-only, default 600; ≥1)."""
    return _int_setting_min("MCA_LESSON_BLOCK_MAX_TOKENS", 600, 1)


def lesson_min_independent_episodes() -> int:
    """`MCA_LESSON_MIN_INDEPENDENT_EPISODES` (env-only, default 3; ≥1).

    Инженерный порог обобщения (GEN-R27) — не доказательство истинности."""
    return _int_setting_min("MCA_LESSON_MIN_INDEPENDENT_EPISODES", 3, 1)


def lesson_relevance_min_score() -> float:
    """`MCA_LESSON_RELEVANCE_MIN_SCORE` (env-only, стартовый 0.34; ≥0).

    Инженерный порог semantic-gate: без связи с задачей урок не проходит
    отбор даже при высоком рейтинге."""
    return _float_setting_min("MCA_LESSON_RELEVANCE_MIN_SCORE", 0.34, 0.0)


def experience_bootstrap_enabled() -> bool:
    """`MCA_EXPERIENCE_BOOTSTRAP_ENABLED` (env-only, default ON).

    ON → bounded bootstrap-часть review-job создаёт только candidate
    historical/unverified (без mass-backfill успеха)."""
    return bool(getattr(settings, "MCA_EXPERIENCE_BOOTSTRAP_ENABLED", True))


# ── mca-09 (ADR-1028-16 D10): K1–K4 Intent/инициативы + env-only лимиты ────
def intents_enabled() -> bool:
    """`MCA_INTENTS_ENABLED` (master, env-only, default ON; K1).

    ON → Intent-контур активен (v29, heartbeat, кандидаты, события).
    OFF → бит-в-бит 2.58.59: ни записей, ни чтений v29, ни heartbeat-джоба,
    ни кандидатов/событий; nostalgia — legacy direct-send."""
    return bool(getattr(settings, "MCA_INTENTS_ENABLED", True))


def intent_heartbeat_enabled() -> bool:
    """`MCA_INTENT_HEARTBEAT_ENABLED` (env-only, default ON; K2).

    Инертен при K1 OFF. ON → due-скан/тик работает. OFF → тик не работает
    (создание/закрытие намерений возможно, due-кандидатов нет)."""
    if not intents_enabled():
        return False
    return bool(getattr(settings, "MCA_INTENT_HEARTBEAT_ENABLED", True))


def intent_decision_enabled() -> bool:
    """`MCA_INTENT_DECISION_ENABLED` (env-only, default ON; K3).

    Инертен при K1 OFF. ON → инициативные решения/делегирование nostalgia
    выполняются. OFF → инициативные решения не выполняются (nostalgia
    legacy), recheck-путь инертен."""
    if not intents_enabled():
        return False
    return bool(getattr(settings, "MCA_INTENT_DECISION_ENABLED", True))


def send_recheck_enabled() -> bool:
    """`MCA_SEND_RECHECK_ENABLED` (env-only, default ON; K4).

    Инертен при K1 OFF. ON → единый `SendRecheck` выполняется на границе
    отправки инициативных/отложенных решений. OFF → новый recheck-слой не
    выполняется (документированное подмножество: существующие гейты)."""
    if not intents_enabled():
        return False
    return bool(getattr(settings, "MCA_SEND_RECHECK_ENABLED", True))


def intent_heartbeat_batch_max() -> int:
    """`MCA_INTENT_HEARTBEAT_BATCH_MAX` (env-only, default 20; ≥1)."""
    return _int_setting_min("MCA_INTENT_HEARTBEAT_BATCH_MAX", 20, 1)


def intent_max_attempts() -> int:
    """`MCA_INTENT_MAX_ATTEMPTS` (env-only, default 3; ≥1)."""
    return _int_setting_min("MCA_INTENT_MAX_ATTEMPTS", 3, 1)


def intent_candidates_max() -> int:
    """`MCA_INTENT_CANDIDATES_MAX` (env-only, default 8; ≥1)."""
    return _int_setting_min("MCA_INTENT_CANDIDATES_MAX", 8, 1)


def intent_retention_days() -> int:
    """`MCA_INTENT_RETENTION_DAYS` (env-only, default 180; ≥1)."""
    return _int_setting_min("MCA_INTENT_RETENTION_DAYS", 180, 1)


def intent_defer_backoff_seconds() -> int:
    """`MCA_INTENT_DEFER_BACKOFF_SECONDS` (env-only, default 1800; ≥60).

    Bounded backoff «не тот момент» — не nag-таймер обязательной речи."""
    return _int_setting_min("MCA_INTENT_DEFER_BACKOFF_SECONDS", 1800, 60)


# ── mca-18 (ADR-1028-18 §8.3): K1–K3 SelfModel + env-only пороги ────────────
def self_model_enabled() -> bool:
    """`MCA_SELF_MODEL_ENABLED` (master K1, env-only, default ON).

    ON → SelfModelSnapshot/resolve/frame/сборка характера активны (блоки A–F).
    OFF → бит-в-бит 2.58.61: промпт собирает legacy
    `build_persona_prompt_block`; v31 SelfModel-контуром не читается/не
    пишется; статусы честные `disabled`."""
    return bool(getattr(settings, "MCA_SELF_MODEL_ENABLED", True))


def trait_rules_enabled() -> bool:
    """`MCA_TRAIT_RULES_ENABLED` (env-only, default ON; K2).

    ON → lifecycle TraitObservation/BehaviorRule + анти-самоусиление + гарды.
    OFF → v31-таблицы черт инертны (ни записей, ни чтений черт; snapshot
    отдаёт пустые traits/state с честным `disabled`)."""
    return bool(getattr(settings, "MCA_TRAIT_RULES_ENABLED", True))


def legacy_traits_migration_enabled() -> bool:
    """`MCA_LEGACY_TRAITS_MIGRATION_ENABLED` (env-only, default ON; K3).

    ON → фоновый идемпотентный разбор `persona_traits` (job mca-01) работает.
    OFF → разбор не запускается (лента/`persona_traits` не меняются)."""
    return bool(getattr(settings, "MCA_LEGACY_TRAITS_MIGRATION_ENABLED", True))


def mood_ttl_seconds() -> int:
    """`MCA_MOOD_TTL_HOURS` (env-only, default 6 ч; ≥1 ч; spec §8.5).

    TTL настроения: обратимая поправка с временем окончания, не
    необратимое изменение личности. Инженерный дефолт (GEN-R27)."""
    return _int_setting_min("MCA_MOOD_TTL_HOURS", 6, 1) * 3600


def trait_max_step_per_cycle() -> float:
    """`MCA_TRAIT_MAX_STEP_PER_CYCLE` (env-only, default 0.1; ≥0).

    Анти-самоусиление (§28.4 `:1562`): максимальный шаг dimension за цикл
    (шкала 0–1). Инженерный дефолт устойчивости (GEN-R27)."""
    return _float_setting_min("MCA_TRAIT_MAX_STEP_PER_CYCLE", 0.1, 0.0)


def trait_max_step_24h() -> float:
    """`MCA_TRAIT_MAX_STEP_24H` (env-only, default 0.2; ≥0).

    Суточный кап шага dimension (0–1); ослабление (delta<0) капом не
    ограничено."""
    return _float_setting_min("MCA_TRAIT_MAX_STEP_24H", 0.2, 0.0)


def self_model_fallback_ttl_seconds() -> int:
    """`MCA_SELF_MODEL_FALLBACK_TTL_SECONDS` (env-only, default 600; ≥0).

    Ограниченный TTL last-known-good snapshot при недоступности PG
    (fallback stale-маркер, §28.5 `:1576`). 0 → LKG не используется
    (TTL обязан быть ограниченным; честный minimal-fallback)."""
    return _int_setting_min("MCA_SELF_MODEL_FALLBACK_TTL_SECONDS", 600, 0)


def random_circuit_fails() -> int:
    """`MCA_RANDOM_CIRCUIT_FAILS` (env-only, default 3; ≥1)."""
    return _int_setting_min("MCA_RANDOM_CIRCUIT_FAILS", 3, 1)


def random_circuit_cooldown_seconds() -> int:
    """`MCA_RANDOM_CIRCUIT_COOLDOWN_SECONDS` (env-only, default 60; ≥1)."""
    return _int_setting_min("MCA_RANDOM_CIRCUIT_COOLDOWN_SECONDS", 60, 1)


def random_min_request_interval_seconds() -> float:
    """`MCA_RANDOM_MIN_REQUEST_INTERVAL_SECONDS` (env-only, default 1.0).

    Минимальный интервал между ANU-запросами (Trial 1 req/s): защита «429
    без запроса на каждое сообщение». Никогда не бросает."""
    return _float_setting_min("MCA_RANDOM_MIN_REQUEST_INTERVAL_SECONDS",
                              1.0, 0.0)


def random_draw_retention_days() -> int:
    """`MCA_RANDOM_DRAW_RETENTION_DAYS` (env-only, default 90; ≥1)."""
    return _int_setting_min("MCA_RANDOM_DRAW_RETENTION_DAYS", 90, 1)


def random_draw_max_rows() -> int:
    """`MCA_RANDOM_DRAW_MAX_ROWS` (env-only, default 10000; ≥1)."""
    return _int_setting_min("MCA_RANDOM_DRAW_MAX_ROWS", 10000, 1)


def random_anu_trial_monthly_limit() -> int:
    """`MCA_RANDOM_ANU_TRIAL_MONTHLY_LIMIT` (env-only, default 100; ≥1).

    Условие Trial перепроверяется при подключении (T-4986); значение —
    только для честной «оценки» остатка, не искусственный лимит бота."""
    return _int_setting_min("MCA_RANDOM_ANU_TRIAL_MONTHLY_LIMIT", 100, 1)


def random_anu_trial_rps() -> int:
    """`MCA_RANDOM_ANU_TRIAL_RPS` (env-only, default 1; ≥1)."""
    return _int_setting_min("MCA_RANDOM_ANU_TRIAL_RPS", 1, 1)


def random_quantum_hex_block_size() -> int:
    """`MCA_RANDOM_QUANTUM_HEX_BLOCK_SIZE` (env-only, default 4; 1..10)."""
    return min(10, _int_setting_min("MCA_RANDOM_QUANTUM_HEX_BLOCK_SIZE", 4, 1))


def chat_stats_occurrence_max_rows() -> int:
    """Кап bounded-скана occurrences (env-only, default 20000; ≥1)."""
    return _int_setting_min("MCA_CHAT_STATS_OCCURRENCE_MAX_ROWS", 20000, 1)


def chat_stats_examples_max() -> int:
    """Кап примеров в измерении (env-only, default 20; ≥1)."""
    return _int_setting_min("MCA_CHAT_STATS_EXAMPLES_MAX", 20, 1)


def style_scope_chat_ttl_days() -> int:
    """TTL chat-просьб, дни (env-only `MCA_STYLE_SCOPE_CHAT_TTL_DAYS`, 7)."""
    return _int_setting("MCA_STYLE_SCOPE_CHAT_TTL_DAYS", 7)


def style_scope_topic_ttl_days() -> int:
    """TTL topic-просьб, дни (env-only `MCA_STYLE_SCOPE_TOPIC_TTL_DAYS`, 30)."""
    return _int_setting("MCA_STYLE_SCOPE_TOPIC_TTL_DAYS", 30)


def _float_setting_min(name: str, default: float,
                       minimum: float = 0.0) -> float:
    """env-only float с нижней границей (никогда не бросает)."""
    try:
        return max(minimum, float(getattr(settings, name, default)))
    except Exception:      # pragma: no cover - защитная ветка
        return default


def _int_setting_min(name: str, default: int, minimum: int = 1) -> int:
    """env-only int с нижней границей (никогда не бросает)."""
    try:
        return max(minimum, int(getattr(settings, name, default)))
    except Exception:      # pragma: no cover - защитная ветка
        return default


def dream_historical_prelimit_factor() -> int:
    """Pre-limit профиля = factor × top_k (≥4 по spec §4.2; env-only)."""
    return _int_setting_min("MCA_DREAM_HISTORICAL_PRELIMIT_FACTOR", 4, 4)


def dream_max_topic_packets() -> int:
    """Bound числа тематических пакетов за прогон (env-only, default 3)."""
    return _int_setting_min("MCA_DREAM_MAX_TOPIC_PACKETS", 3, 1)


def dream_enrich_max_rounds() -> int:
    """Bound раундов resumable enrichment (env-only, default 2)."""
    return _int_setting_min("MCA_DREAM_ENRICH_MAX_ROUNDS", 2, 1)


def dream_enrich_batch_messages() -> int:
    """Размер порции enrichment в сообщениях (env-only, default 50)."""
    return _int_setting_min("MCA_DREAM_ENRICH_BATCH_MESSAGES", 50, 1)


def dream_backoff_seconds(streak: int) -> int:
    """Ограниченный экспоненциальный backoff ошибок (§6.2/§4.4).

    base × 2^(streak-1), cap; streak<1 → base. Никогда не бросает."""
    base = _int_setting_min("MCA_DREAM_BACKOFF_BASE_SECONDS", 3600, 1)
    cap = _int_setting_min("MCA_DREAM_BACKOFF_CAP_SECONDS", 86400, 1)
    try:
        n = max(0, int(streak) - 1)
        return int(min(cap, base * (2 ** min(n, 20))))
    except Exception:      # pragma: no cover - защитная ветка
        return base


def dream_per_chat_attempts_limit() -> int:
    """Суточный per-chat лимит стоимостных попыток (env-only, default 1)."""
    return _int_setting_min("MCA_DREAM_PER_CHAT_ATTEMPTS_LIMIT", 1, 1)


def dream_global_attempts_limit() -> int:
    """Глобальный суточный лимит попыток — защита ресурсов (default 30)."""
    return _int_setting_min("MCA_DREAM_GLOBAL_ATTEMPTS_LIMIT", 30, 1)


# Восемь различимых причин gate'а (spec §3.3).
DREAM_GATE_REASONS = (
    "master_sleep_off", "deep_sleep_off", "rag_off",
    "memory_service_missing", "schedule_outside_window",
    "queue_busy", "cooldown", "resource_limit",
)

# ── D14 (asap5-final-fixes, T-5264, Q11): gate ≠ last-attempt ───────────────
# Scheduler-причины (cooldown/schedule/queue/resource) объясняют ТОЛЬКО почему
# НОВЫЙ запуск не начался и НЕ подменяют результат предыдущей попытки
# (RCA P1: 16×no_anchors за «cooldown» — владелец не видел причину).
SCHEDULER_GATE_REASONS = frozenset({
    "cooldown", "schedule_outside_window", "queue_busy", "resource_limit",
})
# Retry-классы (frozen D14; константы в коде — Δ каталога/KS = 0):
DEEP_RETRY_CONTENT_EMPTY = "content_empty"   # A: обычный интервал
DEEP_RETRY_TECH_ERROR = "tech_error"         # B: bounded backoff (Gate 7a)
DEEP_RETRY_BOOTSTRAP = "bootstrap"           # C: 2 ч / ≤6 сутки, до первой записи
# Контент-пустые статусы (класс A; статусы memory_dream_log).
DEEP_CONTENT_EMPTY_STATUSES = frozenset({
    "no_context", "no_anchors", "insufficient_evidence", "unchanged",
    "duplicate",
})
# Класс C (bootstrap): интервал/кап автопопыток, пока парадигм 0.
DEEP_BOOTSTRAP_INTERVAL_SECONDS = 2 * 3600   # раз в 2 ч
DEEP_BOOTSTRAP_DAILY_CAP = 6                 # максимум 6/сутки


def deep_retry_class(raw_status: str) -> str | None:
    """D14: класс причины последней попытки по сырому статусу
    memory_dream_log. ok/письмо → None (cooldown обычный); контент-пустые →
    A; техошибки (llm/parse/write → status='error') → B. Никогда не бросает."""
    s = str(raw_status or "").strip()
    if not s or s in ("ok", "written"):
        return None
    if s in DEEP_CONTENT_EMPTY_STATUSES:
        return DEEP_RETRY_CONTENT_EMPTY
    if s == "error":
        return DEEP_RETRY_TECH_ERROR
    return None


async def deep_bootstrap_pending(db, chat_id: int | None) -> bool:
    """Класс C активен: парадигм у чата ещё НЕТ (paradigms_total==0).
    Fail-open: ошибка чтения → False (класс C не активируется молча)."""
    if db is None or chat_id is None:
        return False
    try:
        total = int(await db.count_paradigms(int(chat_id)))
    except Exception:
        return False
    return total == 0


async def deep_bootstrap_cap_ok(db, chat_id: int | None, now: int,
                                last_attempt: int | None = None) -> bool:
    """Класс C: интервал (раз в DEEP_BOOTSTRAP_INTERVAL_SECONDS) + суточный
    кап (≤ DEEP_BOOTSTRAP_DAILY_CAP). Считает ВСЕ попытки (вкл. дешёвые
    no_anchors-скипы) — иначе кап был бы фикцией. Fail-open при ошибке
    чтения → False (кап считают исчерпанным)."""
    if db is None or chat_id is None:
        return False
    if last_attempt is not None and \
            (int(now) - int(last_attempt)) < DEEP_BOOTSTRAP_INTERVAL_SECONDS:
        return False            # 2-часовой интервал bootstrap-класса
    try:
        from services.dream_worker import _day_start_ts
        day_start = _day_start_ts(int(now),
                                  getattr(settings, "WORKER_BUDGET_TZ", "UTC"))
        used = await db.count_deep_attempts_all(day_start, chat_id=int(chat_id))
    except Exception:
        return False
    return int(used) < DEEP_BOOTSTRAP_DAILY_CAP


@dataclasses.dataclass(frozen=True)
class DreamGateState:
    """Единый ответ resolver'а сна (spec §3.1, D6).

    `blocked=False` → `gate='none'`, `reason=None`, `effective=True`."""
    gate: str
    blocked: bool
    reason: str | None
    global_value: bool
    chat_override: bool | None
    effective: bool
    source: str
    detail: str | None

    def as_dict(self) -> dict:
        return {
            "gate": self.gate,
            "blocked": bool(self.blocked),
            "reason": self.reason,
            "global_value": bool(self.global_value),
            "chat_override": self.chat_override,
            "effective": bool(self.effective),
            "source": self.source,
            "detail": self.detail,
        }


async def _dream_setting_layer(key: str, chat_id: int | None, default):
    """(effective, global, chat_override, source, read_error) для одного ключа.

    `chat_override` = bool(value) если source=='chat', иначе None. Читает через
    `resolve_setting_with_source` (никогда не бросает — fail-open 'error')."""
    from services.worker_settings import resolve_setting_with_source
    try:
        eff, src = await resolve_setting_with_source(
            key, chat_id=chat_id, default=default)
    except Exception:      # pragma: no cover - защитная ветка
        return bool(default), bool(default), None, "error", True
    err = str(src) == "error"
    override = None
    gv = eff
    if str(src) == "chat":
        override = bool(eff)
        try:
            gv, _ = await resolve_setting_with_source(
                key, chat_id=None, default=default)
        except Exception:      # pragma: no cover - защитная ветка
            gv = eff
    return bool(eff), bool(gv), override, str(src), err


def _blocked(gate: str, reason: str, *, global_value: bool = False,
             chat_override: bool | None = None, effective: bool = False,
             source: str = "default", detail: str | None = None
             ) -> DreamGateState:
    return DreamGateState(gate=gate, blocked=True, reason=reason,
                          global_value=bool(global_value),
                          chat_override=chat_override,
                          effective=bool(effective), source=source,
                          detail=detail)


def _unblocked() -> DreamGateState:
    return DreamGateState(gate="none", blocked=False, reason=None,
                          global_value=True, chat_override=None,
                          effective=True, source="default", detail=None)


async def _schedule_gate(chat_id: int | None, now: int,
                         worker=None) -> DreamGateState | None:
    """Gate 5: вне расписания/окна сна. `after_sleep` всегда открыт (запуск
    по завершении обычного сна); `fixed` — только в свой local-час."""
    from services.worker_settings import resolve_setting_cached
    try:
        trigger = str(await resolve_setting_cached(
            "memory.deep_sleep_trigger", chat_id=chat_id,
            default=settings.DEEP_SLEEP_TRIGGER) or "after_sleep")
    except Exception:      # pragma: no cover - fail-open
        return None
    if trigger != "fixed":
        return None
    try:
        target = int(await resolve_setting_cached(
            "memory.deep_sleep_hour", chat_id=chat_id,
            default=settings.DEEP_SLEEP_HOUR) or 7)
    except Exception:      # pragma: no cover - fail-open
        return None
    tz = None
    if worker is not None:
        tz = getattr(worker, "_deep_tz_name", None)
    tz = tz or getattr(settings, "WORKER_BUDGET_TZ", "UTC")
    try:
        from services.dream_worker import _local_hour
        hour = int(_local_hour(now, tz))
    except Exception:      # pragma: no cover - защитная ветка
        return None
    if hour != target:
        return _blocked(
            "schedule", "schedule_outside_window", global_value=True,
            effective=False, source="default",
            detail=(f"memory.deep_sleep_trigger=fixed, "
                    f"memory.deep_sleep_hour={target}, now_hour={hour}"))
    return None


async def _cooldown_gate(db, chat_id: int | None, now: int) -> DreamGateState | None:
    """Gate 7: cooldown завершённого прогона/попытки (per-chat).

    Ошибка чтения НЕ глотается — вызывающий (worker) уходит в legacy-ветку
    fail-safe `cooldown_read` (паритет безопасности 2.58.48)."""
    if db is None or chat_id is None:
        return None
    # Gate 7a: ограниченный экспоненциальный backoff ошибок (T-4724, §6.2).
    # Причина та же (`cooldown`), но `detail` различим (`backoff`), не
    # склеивается с обычным cooldown. Сброс — новые dream-данные после
    # последней ошибки; окно пересчитывается из текущих env-настроек.
    if dream_quotas_split_enabled():
        last_err = None
        streak = 0
        try:
            last_err, streak = await db.deep_error_state(chat_id)
        except Exception:      # pragma: no cover - защитная ветка
            last_err = None
        if last_err is not None:
            window = dream_backoff_seconds(streak or 1)
            if (int(now) - int(last_err)) < int(window):
                new_data = None
                try:
                    new_data = await db.latest_dream_data_ts(chat_id)
                except Exception:      # pragma: no cover - защитная ветка
                    new_data = None
                if new_data is None or int(new_data) <= int(last_err):
                    return _blocked(
                        "cooldown", "cooldown", global_value=True,
                        effective=False, source="runtime",
                        detail=(f"backoff: streak={streak}, "
                                f"last_error={int(last_err)}, "
                                f"window={int(window)}s"))
    last = await db.last_deep_attempt(chat_id)
    if last is None:
        return None
    from services import dream_worker as _dw
    cooldown_h = _dw._hot_number(
        "memory.deep_sleep_min_interval_hours",
        _dw._DEEP_SLEEP_MIN_INTERVAL_HOURS, int)
    if (int(now) - int(last)) < int(cooldown_h) * 3600:
        # D14/T-5264, класс C (bootstrap): парадигм у чата ещё нет —
        # автопопытка раз в DEEP_BOOTSTRAP_INTERVAL_SECONDS (вместо полного
        # 20-часового интервала), с капом DEEP_BOOTSTRAP_DAILY_CAP/сутки
        # (считаются ВСЕ попытки). Не busy-loop: интервал + кап; до первой
        # записи. LLM-защита (resource gate) не ослабляется.
        if await deep_bootstrap_pending(db, chat_id) \
                and await deep_bootstrap_cap_ok(db, chat_id, int(now),
                                                last_attempt=int(last)):
            return None
        return _blocked(
            "cooldown", "cooldown", global_value=True, effective=False,
            source="runtime",
            detail=(f"memory.deep_sleep_min_interval_hours={cooldown_h}, "
                    f"last_attempt={int(last)}"))
    return None


async def _resource_gate(db, chat_id: int | None, now: int) -> DreamGateState | None:
    """Gate 8: суточный лимит стоимостных попыток (T-4723, §6.1, D9/О3).

    Двухуровнево при `MCA_DREAM_QUOTAS_SPLIT_ENABLED` ON:
      * per-chat доступность — `count_deep_attempts(chat_id=…)` ×
        `MCA_DREAM_PER_CHAT_ATTEMPTS_LIMIT`;
      * глобальная защита — глобальный `count_deep_attempts` ×
        `MCA_DREAM_GLOBAL_ATTEMPTS_LIMIT` (сохраняется, не снимается).
    Обе причины `resource_limit`, `detail` различает per-chat/глобальный.
    OFF → прежний глобальный путь (`MCA_DREAM_DAILY_ATTEMPTS_LIMIT`, default 1,
    паритет 2.58.48). Ошибка чтения НЕ глотается — вызывающий уходит в legacy
    fail-safe."""
    if db is None:
        return None
    from services.dream_worker import _day_start_ts
    tz = getattr(settings, "WORKER_BUDGET_TZ", "UTC")
    day_start = _day_start_ts(now, tz)
    if dream_quotas_split_enabled() and chat_id is not None:
        used_chat = await db.count_deep_attempts(day_start, chat_id=chat_id)
        limit_chat = dream_per_chat_attempts_limit()
        if int(used_chat) >= int(limit_chat):
            return _blocked(
                "resource", "resource_limit", global_value=True,
                effective=False, source="runtime",
                detail=(f"per-chat daily deep attempts: used={used_chat}, "
                        f"limit={limit_chat}, chat_id={int(chat_id)}"))
        limit_global = dream_global_attempts_limit()
    else:
        limit_global = _int_setting_min("MCA_DREAM_DAILY_ATTEMPTS_LIMIT", 1, 1)
    used = await db.count_deep_attempts(day_start)
    if int(used) >= int(limit_global):
        return _blocked(
            "resource", "resource_limit", global_value=True,
            effective=False, source="runtime",
            detail=f"global daily deep attempts: used={used}, limit={limit_global}")
    return None


async def resolve_dream_gate(db, chat_id: int | None, *, memory=_UNSET,
                             worker=None, now: int | None = None,
                             manual: bool = False, inside_run: bool = False,
                             include_master: bool = True,
                             include_deep: bool = True,
                             queue_busy: bool | None = None) -> DreamGateState:
    """Единый effective-config/gate ответ для сна (spec §3.1–3.3, D1).

    Порядок фиксирован (§3.2): memory_service_missing → master_sleep_off →
    deep_sleep_off → rag_off → schedule_outside_window → queue_busy →
    cooldown → resource_limit. Первый сработавший gate — возвращаемая причина.

    `include_master=False` — deep-контур (у глубокого сна собственный гейт
    `flags.deep_sleep_enabled`; ordinary-sleep master не блокирует deep).
    `manual=True` — ручной диагностический запуск: schedule/queue/cooldown/
    resource не блокируют (паритет прежнего `if not manual`).
    `inside_run=True` — вызов из уже удерживаемого прогона (queue-гейт не
    проверяется — иначе self-deadlock)."""
    if now is None:
        now = int(time.time())
    if memory is _UNSET:
        memory = getattr(worker, "memory", None)
    # 1. memory_service_missing
    if memory is None:
        return _blocked(
            "memory_service", "memory_service_missing", source="runtime",
            detail="DreamWorker.memory is None (сервис памяти не подключён)")
    # 2. master_sleep_off
    if include_master:
        eff, gv, ov, src, err = await _dream_setting_layer(
            "memory.dream_enabled", chat_id, settings.DREAM_ENABLED)
        if not eff:
            return _blocked(
                "master_sleep", "master_sleep_off", global_value=gv,
                chat_override=ov, effective=eff, source=src,
                detail=(f"memory.dream_enabled={eff} (source={src}"
                        + ("; config read failed" if err else "") + ")"))
    # 3. deep_sleep_off
    if include_deep:
        eff, gv, ov, src, err = await _dream_setting_layer(
            "flags.deep_sleep_enabled", chat_id, settings.DEEP_SLEEP_ENABLED)
        if not eff:
            return _blocked(
                "deep_sleep", "deep_sleep_off", global_value=gv,
                chat_override=ov, effective=eff, source=src,
                detail=(f"flags.deep_sleep_enabled={eff} (source={src}"
                        + ("; config read failed" if err else "") + ")"))
    # 4. rag_off
    eff, gv, ov, src, err = await _dream_setting_layer(
        "flags.graph_rag_enabled", chat_id, settings.GRAPH_RAG_ENABLED)
    if not eff:
        return _blocked(
            "rag", "rag_off", global_value=gv, chat_override=ov,
            effective=eff, source=src,
            detail=(f"flags.graph_rag_enabled={eff} (source={src}"
                    + ("; config read failed" if err else "") + ")"))
    # 5. schedule_outside_window
    if not manual:
        sched = await _schedule_gate(chat_id, now, worker)
        if sched is not None:
            return sched
    # 6. queue_busy
    if not manual and not inside_run:
        busy = queue_busy
        if busy is None and worker is not None:
            lock = getattr(worker, "_deep_lock", None)
            busy = bool(getattr(worker, "deep_running", False)
                        or (lock is not None and lock.locked()))
        if busy:
            return _blocked(
                "queue", "queue_busy", source="runtime",
                detail="конкурирующий глубокий прогон уже выполняется")
    # 7. cooldown
    if not manual:
        cd = await _cooldown_gate(db, chat_id, now)
        if cd is not None:
            return cd
    # 8. resource_limit
    if not manual:
        res = await _resource_gate(db, chat_id, now)
        if res is not None:
            return res
    return _unblocked()


# ── mca-19 (ADR-1028-19 §8.3/D13): kill-switch'и Vision + env-only лимиты ──
# Ровно 4 рубильника фичи (76→80); резолв per-call, никогда не бросают.
# Инертности: master OFF ⇒ auto/backfill/tool недостижимы. Каталоговый
# тумблер владельца (flags.vision_enabled) резолвится в
# services/mca_vision.py::resolve_effective_state (requested vs effective).

def vision_enabled() -> bool:
    """`MCA_VISION_ENABLED` (мастер, env-only, default ON; K1).

    ON → модуль распознавания изображений существует (intake-активы,
    анализы, effective-статус). OFF → бит-в-бит 2.58.62."""
    return bool(getattr(settings, "MCA_VISION_ENABLED", True))


def vision_auto_enabled() -> bool:
    """`MCA_VISION_AUTO_ENABLED` (env-only, default ON; K2; инертен при K1).

    ON → автоочередь новых изображений разрешена. OFF → новые авто-задания
    не создаются (ручной/tool путь не гейтится этим рубильником)."""
    if not vision_enabled():
        return False
    return bool(getattr(settings, "MCA_VISION_AUTO_ENABLED", True))


def vision_backfill_enabled() -> bool:
    """`MCA_VISION_BACKFILL_ENABLED` (env-only, default ON; K3; инертен при K1).

    ON → архивный backfill старых изображений разрешён. OFF → backfill
    не запускается (новые изображения — отдельно, K2)."""
    if not vision_enabled():
        return False
    return bool(getattr(settings, "MCA_VISION_BACKFILL_ENABLED", True))


def vision_tool_enabled() -> bool:
    """`MCA_VISION_TOOL_ENABLED` (env-only, default ON; K4; инертен при K1).

    ON → tool recognize_image доступен в общем пуле tool calling (при
    effective-ON модуля). OFF → инструмент скрыт из набора; сервер всё
    равно проверяет OFF для устаревших вызовов (defence in depth)."""
    if not vision_enabled():
        return False
    return bool(getattr(settings, "MCA_VISION_TOOL_ENABLED", True))


def vision_max_bytes() -> int:
    """`MCA_VISION_MAX_BYTES` (env-only, default 20 MiB): аварийный потолок
    размера загрузки; клампит владельческие значения (spec §8.4)."""
    return _int_setting_min("MCA_VISION_MAX_BYTES", 20 * 1024 * 1024, 1)


def vision_max_pixels() -> int:
    """`MCA_VISION_MAX_PIXELS` (env-only, default 25 Mpx): потолок
    декодированных пикселей — decompression-bomb protection (TH-4)."""
    return _int_setting_min("MCA_VISION_MAX_PIXELS", 25_000_000, 1)


def vision_download_concurrency() -> int:
    """`MCA_VISION_DOWNLOAD_CONCURRENCY` (env-only, default 4): лимит
    одновременных загрузок изображений."""
    return _int_setting_min("MCA_VISION_DOWNLOAD_CONCURRENCY", 4, 1)


def vision_deferred_ttl_hours() -> int:
    """`MCA_VISION_DEFERRED_TTL_HOURS` (env-only, default 24): срок жизни
    отложенных заданий (истечение → skipped с причиной)."""
    return _int_setting_min("MCA_VISION_DEFERRED_TTL_HOURS", 24, 1)


def vision_capability_ttl_hours() -> int:
    """`MCA_VISION_CAPABILITY_TTL_HOURS` (env-only, default 6): TTL кеша
    capabilities (ключ provider/endpoint/model/config_revision)."""
    return _int_setting_min("MCA_VISION_CAPABILITY_TTL_HOURS", 6, 1)


def vision_reocr_budget() -> int:
    """`MCA_VISION_REOCR_BUDGET` (env-only, default 2): бюджет повторных
    чтений сомнительного фрагмента (без бесконечной самопроверки)."""
    return _int_setting_min("MCA_VISION_REOCR_BUDGET", 2, 0)


# ── mca-20 (ADR-1028-20 §8.3/D13): kill-switch'и Temporal Factcheck + ──────
# env-only лимиты. Ровно 3 рубильника фичи (80→83); резолв per-call, никогда
# не бросают. Инертности: master OFF ⇒ tool/кеш вердиктов недостижимы
# (легаси-путь хендлера живёт без envelope-контура).

def temporal_factcheck_enabled() -> bool:
    """`MCA_TEMPORAL_FACTCHECK_ENABLED` (мастер, env-only, default ON; K1).

    ON → envelope-пайплайн временного фактчека существует (TemporalClaim
    Envelope/cascade/кеш `factcheck_temporal`/run v33). OFF → бит-в-бит
    d298f1f/2.58.63 (легаси-путь хендлера)."""
    return bool(getattr(settings, "MCA_TEMPORAL_FACTCHECK_ENABLED", True))


def temporal_factcheck_tool_enabled() -> bool:
    """`MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED` (env-only, default ON; K2;
    инертен при K1).

    ON → tool `fact_check` доступен в общем пуле tool calling. OFF →
    инструмент скрыт из набора; сервер всё равно проверяет OFF для
    устаревших вызовов (defence in depth)."""
    if not temporal_factcheck_enabled():
        return False
    return bool(getattr(settings, "MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED", True))


def temporal_factcheck_cache_enabled() -> bool:
    """`MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED` (env-only, default ON; K3;
    инертен при K1).

    ON → готовые вердикты кешируются под slug `factcheck_temporal` (при
    построимом ключе). OFF → всегда вычислять без кеширования вердиктов;
    кеш поиска/загрузок не затрагивается."""
    if not temporal_factcheck_enabled():
        return False
    return bool(getattr(settings, "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED", True))


def temporal_max_runs_list() -> int:
    """`MCA_TEMPORAL_MAX_RUNS_LIST` (env-only, default 50): потолок выборки
    runs для виджета «Аналитики» (защита выборки v33)."""
    return _int_setting_min("MCA_TEMPORAL_MAX_RUNS_LIST", 50, 1)


def temporal_max_evidence_per_run() -> int:
    """`MCA_TEMPORAL_MAX_EVIDENCE_PER_RUN` (env-only, default 20): потолок
    evidence-строк на прогон (защита от раздувания v33)."""
    return _int_setting_min("MCA_TEMPORAL_MAX_EVIDENCE_PER_RUN", 20, 1)


# ── mca-12 (ADR-1028-21 §8.3/D13): kill-switch'и витрины «Истории чата» ─────
# Ровно 2 рубильника фичи (83→85); резолв per-call, никогда не бросают.
# Гейты независимы по осям: K1 — read-контур (витрина+read-API+витрины
# T-5169), K2 — мутационный контур. `MCA_EPISODES_ENABLED` (жизненный цикл
# фасада mca-05) уважается, не дублируется.

def stories_vitrina_enabled() -> bool:
    """`MCA_STORIES_VITRINA_ENABLED` (мастер read-контура, env-only,
    default ON; K1).

    ON → блок «Истории чата» + read-API `/api/stories*` + витрины смежных
    T-5169 существуют. OFF → блок скрыт, read-API — честный disabled
    (не 404-заглушка)."""
    return bool(getattr(settings, "MCA_STORIES_VITRINA_ENABLED", True))


def stories_manage_enabled() -> bool:
    """`MCA_STORIES_MANAGE_ENABLED` (мутационный контур, env-only,
    default ON; K2; независим от K1).

    ON → POST `/api/stories/{id}/action` доступен (под RBAC/CAS). OFF →
    только просмотр; действие отклоняется честным disabled (409). Фасад
    mca-05 не выключается этим рубильником."""
    return bool(getattr(settings, "MCA_STORIES_MANAGE_ENABLED", True))
