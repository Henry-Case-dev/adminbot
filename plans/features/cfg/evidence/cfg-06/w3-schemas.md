# CFG-06 W3 — фриз схем (join-barrier) и миграционные флаги

Дата: 20.10.2026. Код-контракты: `services/factcheck_orchestrator.py` (v2),
`services/factcheck_context.py` (W1), `services/factcheck_suitability.py` (W2).
Заморозка тестами: `tests/test_factcheck_orchestrator_cfg06.py::TestSchemaFreeze`
(+ перекрёстный `test_w1w2_schemas_unchanged`), CONTRACT owner=CFG-06.

## 1. Пайплайн (06H.2) и владение схемами по волнам

```
FactcheckRequest → [ResolveTimeAndProvenance (всегда, build_envelope)]
                 → [Context (W1 ConversationContext) + Suitability (W2 Decision)]
                 → FactcheckPlan (route=внутренняя ветка)
                 → ветка: check_claim_envelope | check_claim
                 → CheckedVerdict (internal, служебные поля разрешены)
                 → build_presentation → FactcheckPresentation (egress)
                 → Delivery (send_chunked_reply; W5: renderer+parse_mode)
```

| Схема | Волна-владелец | Потребители | Поля (заморожены) |
|---|---|---|---|
| `FactcheckRequest` | W3 | handler, W4/W5 | chat_id, trigger_tg_message_id, target_tg_message_id, target_text, user_hint, forward_source, kind, source_type, default_mode |
| `FactcheckPlan` | W3 | W4 (расширяет retrieval-часть ТОЛЬКО аддитивно) | route, context_mode, scope, temporal_hint, cache_slug, fallback_allowed, plan_version |
| `EvidenceRef` | W3 (форма ev-N от mca-20) | **W4** (наполнение: url/support/даты/relaevance), W5 (рендер ссылок) | evidence_id, url, support, source_kind, published_at |
| `EvidenceMap` | W3 | W4 (refs), W5 (links()) | refs, allowlist |
| `CheckedVerdict` | W3 | W4 (verdict-механика), W5 (источник текста) | verdict_text, route, factual_verdict, temporal_status, evaluated_period, uncertainty, evidence, reason_code, as_of, gate_version, fallback_used, cache_hit, already_delivered |
| `FactcheckPresentation` | W3 | **W5** (renderer заполняет parse_mode, links→текст) | text, links, reply_to_message_id, parse_mode, notice |
| `ConversationContext` / `ContextMessage` | W1 | W2, gate W3 | см. TestSchemaFreeze.test_w1w2_schemas_unchanged |
| `ClaimItem` / `SuitabilityDecision` | W2 | gate-маршруты W3 | decision, claim_type, claim_items, scope, reason_code, confidence, target_ref, temporal_hint, gate_version |

Правила фриза: изменение набора полей любой схемы = осознанный bump версии
(`fcv2`/`fcx1`/`fsg1`) + согласие W4∥W5-лейнов; ДОБАВЛЕНИЕ поля — аддитивно
с default (не ломает asdict-фриз только при явном обновлении фриз-теста в
том же PR); ПЕРЕИМЕНОВАНИЕ/УДАЛЕНИЕ — запрещено до W7 без review.

## 2. Egress-whitelist (06B: «не выпускает служебные данные»)

- Граница: `CheckedVerdict` (internal — as_of/gate_version/reason_code/
  enum-статусы) → `build_presentation` → `FactcheckPresentation` (egress —
  служебных полей НЕТ по построению).
- Негатив-тесты: `test_service_fields_do_not_reach_presentation`
  (as_of/gate_version/reason_code/верdict-enum отсутствуют в asdict), 
  `test_egress_scan_strips_service_markers_from_text` (латиница-маркеры
  `gate_version|reason_code|temporal_status|factual_verdict|evaluated_period|
  evidence_refs|as_of|plan_version` срезаются из текста).
- W5 renderer: ссылки — ТОЛЬКО `presentation.links` (URL из EvidenceMap
  текущего прогона); подтверждено `test_envelope_branch_cache_and_links`
  (URL не попадает в plain-текст до renderer'а).

## 3. Флаги: консолидация (старое → новое)

| Флаг | Волна | Значение внутри v2 |
|---|---|---|
| `FACTCHECK_WIDE_CONTEXT_ENABLED` / hot `flags.factcheck_wide_context` | W1 | подразумевается (v2 всегда строит ConversationContext) |
| `FACTCHECK_SUITABILITY_GATE_ENABLED` / hot `flags.factcheck_suitability_gate` | W2 | подразумевается (gate обязателен) |
| `FACTCHECK_PIPELINE_V2_ENABLED` / hot `flags.factcheck_pipeline_v2` | **W3 — единый миграционный рубильник, default OFF** | включает оркестратор |

Матрица откат-безопасности (все горячие, без рестарта):

| W1 | W2 | W3 (v2) | Поведение |
|---|---|---|---|
| OFF | OFF | OFF | **прод 2.58.98 байт-в-байт** (текущий default) |
| ON | OFF | OFF | + широкий контекст (W1-инкремент) |
| ON | ON | OFF | + suitability gate (W2-инкремент, короткие canned-реплики) |
| * | * | ON | **единый pipeline v2** (wide+gate внутри, persona-реплики, egress-whitelist, единый delivery) |

Порядок включения при выкате: v2 ON самодостаточен (W1/W2-флаги внутри v2 не
читаются); откат v2 OFF → предыдущий режим по W1/W2-флагам. Три рубильника
остаются независимыми kill-switch'ами (не поля каталога MiniApp — Δ каталога 0).

## 4. Маршруты внутри v2 (06H.5: развилка — внутренняя, не продуктовая)

- `envelope_temporal`: envelope построен И K1 `temporal_factcheck_enabled`;
  составной кеш `factcheck_temporal` (as_of внутри payload), run-запись v33,
  EvidenceMap из run.evidence_rows.
- `legacy_single` (fallback/откат): ТОТ ЖЕ вызов `service.check_claim` с теми
  же аргументами, что прод-путь (тест `test_legacy_branch_same_call_args_as_prod`),
  slug `factcheck`, запись после доставки (59.2), EvidenceMap пуст.
- Gate-маршруты (ДО поиска): `no_claim_after_context` → canned-пул
  `FACTCHECK_NO_CLAIM_PHRASES`; `ambiguous_needs_clarification` →
  персона-уточнение (`speech_owner_block` ПОСЛЕДНИМ блоком system, шов
  MCA-08; тест `test_ambiguous_persona_reply_with_owner_block_last`),
  fallback — пул `FACTCHECK_CLARIFY_PHRASES`; `context_unavailable` →
  продолжение как сегодня (не отказ, 06I.8).
- Ошибки — те же семантики фраз: 🗿/5.4b/5.5 (тест-покрытие через исключения
  сервис-мока; фразы идентичны legacy).

## 5. Промпт-каноны (пункт 6 брифа)

Каноны `factcheck_prompts.py`/`prompt_registry.py` НЕ тронуты: гейт/CR
детерминированы; единственный новый текст — inline-инструкция короткой
персона-реплики внутри оркестратора (`_SHORT_REPLY_INSTRUCTION`, НЕ элемент
канона/реестра). Протокол ADR-1013-3 не требуется — FROZEN-база не менялась.

## 6. Границы W3 → W4∥W5

- W4: наполняет EvidenceMap структурированным поиском (url отдельно от
  текста), смысловые запросы, SafeFetcher; план-route остаётся внутренней
  веткой.
- W5: `FactcheckPresentation.parse_mode`/links → безопасный renderer +
  entity-safe доставка; `notice` — честное ограничение.
- W6: консолидация трасс/метрик (сейчас: logger + stage_event на
  gate-маршрутах), миграция/инвалидация двух кешей.
