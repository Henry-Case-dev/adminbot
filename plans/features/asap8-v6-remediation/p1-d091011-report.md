# P1-D091011 — отчёт лейна (ASAP 8 v6, P1: D09-остаток + D10 + D11)

Baseline: master `2ef6189` (HEAD на старте лейна). Режим: writer (leaf),
WRITE_SCOPE соблюдён. Ничего не закоммичено (хендофф Orchestrator).

## 1. D09-остаток — Dream/Deep Sleep/freshness/GraphRAG/панели

### D09.1 — Dream groups: deferred-очередь + exactly-once (§18F.1, M8)

**Симптом (был):** qualified-кластеров больше `dream_max_clusters_per_run` →
top-K дистиллируется, а `_finish_chat` двигал watermark по ВСЕМ строкам батча —
необработанные eligible группы помечались завершёнными навсегда; при
window/budget-стопе обработанные группы передистиллировались повторным тиком.

**Фикс (`services/dream_worker.py`):**
- durable-очередь отложенных групп на существующем аудите
  `memory_dream_log` (status=`cluster_deferred`, отпечаток = source_ids
  дистилляционного вида `order_dream_rows` с капой 25); разрешение очереди —
  более поздняя строка `distilled/ok` или `skipped/unchanged` с тем же
  отпечатком. Схема БД НЕ менялась;
- watermark при успешном неполном прогоне останавливается перед фактами
  необработанных eligible групп (`_safe_watermark`: min(id) − 1, floor =
  текущий watermark, назад не двигаем); при error-стопе — прежняя заморозка
  до упавшего кластера (теперь с floor-гардом);
- exactly-once: группы с финальным исходом в журнале (`done`-отпечатки)
  повторно НЕ дистиллируются (0 LLM-вызовов) — чинит и латентный дубль при
  window/budget-stop → resume;
- приоритет FIFO очереди при ранжировании следующего прогона;
- новый счётчик `deferred` в результате чата/тика (для панелей/статуса).

**RED:** stash-прогон на старом коде — 3/5 тестов падают (главный M8-тест +
2 unit). PASS: 5/5 (`tests/test_asap8_v6_p1_d09_dream.py`, REGRESSION,
owner=ASAP8-v6/D09) — 3+ прогона обрабатывают 7 групп при лимите 2/прогон
ровно по разу (ровно 7 LLM-вызовов), watermark не проходит мимо
необработанных, очередь без дублей.

**Обновлённый пин:** `tests/test_dream_worker.py::
test_distillations_budget_per_day_and_reset` — старое тело закрепляло
ПОВТОРНУЮ дистилляцию тех же групп на «день 2» (4 повторных LLM-вызова) —
это противоречит контракту §18F.1 «exactly once». Тест дополнен 5-й темой:
все исходные утверждения (budget reset, budget_stop, счётчики вызовов)
сохранены, пере-дистилляции больше нет (ровно 4 вызова суммарно).

### D09.2 — Deep Sleep stage truth (§18F.6, M13)

**Было:** `_rep(stage="bridge", "succeeded")` ставился сразу после LLM-вызова
(даже при no-response), `_rep(stage="write", "succeeded")` — безусловно после
цикла записи (даже при all-write-failed). Стадии report_json лгали.

**Фикс (`services/dream_worker.py::_run_deep_once_core`):**
- `bridge`: succeeded только при непустом ответе; no-response →
  `failed/no_response`;
- новая стадия `validate`: succeeded после валидного parse (+мост-валидатор);
  parse-ошибка → `failed/parse_error|no_response`; «нет новых выводов» →
  нейтральный `skipped/no_new_insight`; insufficient_evidence →
  `skipped/insufficient_evidence`;
- `write`: succeeded только при `written > 0`; all-write-failed →
  `failed/all_write_failed`; все дубли → `skipped/all_duplicates`;
- `_rep` расширен: `stage_reason` попадает в запись стадии (R17-коды).
Терминальные статусы прогона не менялись (уже честные).

**RED:** 5/5 падают на старом коде. PASS: 5/5
(`tests/test_asap8_v6_p1_d09_deep_stages.py`, REGRESSION, M13) — на durable
отчёте `mca_pipeline_runs.report_json`.

### D09.3 — Broad memory freshness (§18F.3, M10)

**Было:** L2 «широкий фон» (`_build_level2`) гарделся только
`msg_count_highwater >= raw_count` — новое окно ТОГО ЖЕ размера (500
сообщений) с новым контентом навсегда пропускалось.

**Фикс (`services/summary_memory.py`):** идентичность источника L2 —
диапазон prev-L1 `(window_end_ts, raw_count)`, не размер окна:
- точный повтор диапазона → работы нет (LLM не зовётся);
- устаревший (меньший) диапазон не перезаписывает свежий;
- версия источника персистится в существующей `task_jobs` kv
  (прецедент intent_heartbeat_liveness, `summary_l2_source_version:<chat>`) —
  capture-before-await (identity зафиксирован ДО LLM, пишется после UPSERT);
  fail-open: нет версии → прежний count-гард (легаси-совместимость).
Схема БД НЕ менялась.

**RED:** 3/4 M10-тестов падают на старом коде (равное окно не обновлялось).
PASS: `tests/test_asap8_v6_p1_d09_memory.py::TestBroadContextFreshness` —
равное окно обновляет, точный повтор не создаёт работу, stale не
перезаписывает, легаси-гард работает.

### D09.4 — GraphRAG outcomes (§18F.5, M12)

**Было:** `_memorize_facts_inner` возвращал `status="success"` даже когда все
записи упали (saved=0, skipped=N) — «успех с нулём персистенции»; неудачная
запись факта терялась молча.

**Фикс (`services/summary_memory.py`):**
- исход прогона из ФАКТИЧЕСКОЙ персистенции: `all_duplicates`
  (saved=0, skipped=0, deduped>0 — нейтральный, не потеря), `write_failed`
  (saved=0, skipped>0 — честный failed), `partial` (mixed),
  `text_only_vector_deferred` (факты живы текстом, векторы отложены),
  `success`, `no_new_facts` (пустой валидный extract);
- bounded retry записи факта (1 повтор транзакции fact+edge) до честного
  write_failed — единичный БД-сбой больше не теряет факт;
- терминал `FACTS_EXTRACT`: enum события закрытый (mca-13), различие M12
  несёт `reason_code` + `usage_json.outcome` (+счётчики): write_failed →
  outcome failed/WARN (writer_failed), partial → success/WARN (run_partial),
  text_only → success/WARN (embed_deferred), all_duplicates → success/INFO.
  Существующие пины (success/skipped/failed + коды) не сломаны.

**RED:** 6/9 M12-тестов падают на старом коде. PASS:
`tests/test_asap8_v6_p1_d09_memory.py::TestGraphRagOutcomes` — 4 исхода
различимы, retry без потерь, дубликаты нейтральны.

### D09.5 — Панели (минимально, существующие поля)

- `web/app.js`: карта `DREAM_STATUS_LABELS` (модульная константа) +
  `dreamStatusLabel()` (неизвестный код — честный raw) +
  `dreamStatusBadgeClass()` (ok+distilled → badge-ok; unchanged/duplicate →
  badge-muted; error/deferred/скипы → badge-warn);
- `web/index.html`: панель «Последние сны (прогоны/причины)» на Обзоре
  workspace «Сон» (`data-dream-panel`, прецедент инициативного блока C06A).
  Найденный в ходе работы разрыв: старая панель жила только в легаси-модалке
  (`activeModule`/`openModuleWindow`), недостижимой из текущего workspace-UI
  (кнопка «Настроить» уводит в workspace, а не в модалку) — панель
  перенесена на рабочую поверхность Обзора; данные грузятся существующим
  `applyRoute → _ensureModuleData → loadDreamLog`. Deferred-статусы очереди
  D09.1 видны в панели человекочитаемо.
- JS-unit: `tests/js/asap8_v6_p1_d09_panels_test.js` → `P1-D09-PANELS-UNIT-OK`.

## 2. D10 — Temporal factcheck evidence integrity (§18G)

`services/temporal_factcheck.py`:
- стабильные current-run ID `ev-N` в `evidence_rows_from_results`
  (+`date_parse_status="unknown"` default);
- `parse_publication_date(html, url)`: meta property/name/itemprop →
  JSON-LD datePublished → `<time datetime>` → путь URL `/YYYY/MM/DD/`;
  ISO 8601/RFC 2822; sanity-границы [1990, now+1д] (now — только граница
  валидности, никогда значение);
- `enrich_evidence_dates(evidence, fetch_text=...)`: bounded fetch
  (≤5 URL, SafeFetcher html-профиль 64KB/4s, gather) существующим
  fetch-механизмом; success → `published_at` + `published_at_source`
  (html_meta/json_ld/html_time/url_path) + `date_parse_status=parsed`;
  failure → `date_parse_status=failed` + `date_parse_reason=date_parse_failed`,
  published_at остаётся None — **now() никогда не подставляется**; сбой fetch
  = failed, pipeline не прерывается; env `TEMPORAL_EVIDENCE_DATE_FETCH_ENABLED`
  (default ON), OFF в юнит-контурах mca-20 (autouse-фикстуры в 3 файлах);
- `verdict_from_payload(..., allowed_refs=...)`: §18G.3 — evidence_refs
  валидируются по current-run allowlist стабильных ID; invented ID/
  произвольный service text отбрасываются;
- `TEMPORAL_ANALYST_SYSTEM`: правило (8) — refs только ID из `<evidence>`;
- repost/original раздельность сохранена (envelope: repost_received_at ≠
  original_published_at; evidence: published_at ≠ retrieved_at; колонки v33
  без изменений — published_at_source несёт источник/`date_parse_failed`).

`services/factcheck_service.py`:
- `check_claim_envelope`: enrich после evidence-построения (gated, fail-open);
- payload аналитика/валидатора: секция `<evidence>` с `[ev-N] published:
  YYYY-MM-DD|unknown` (инъекция остаётся данными — пин контейнера обновлён с
  `<search_results>` на `<evidence>` по сути секции);
- allowlist передаётся во ВСЕ ТРИ call sites `verdict_from_payload`:
  (1) primary-вердикт аналитика, (2) результат apply_validator-мержа
  (тот же серверный guard), (3) fallback-повтор аналитика после провала
  validator'а (:578) — REV-P1 High: третий call site изначально был пропущен
  (invented `ev-9` протекал в durable вердикт через fallback-путь; RED
  воспроизведён: `('ev-1', 'ev-9')` без фикса → `('ev-1',)` с фиксом);
- `_TEMPORAL_FALLBACK_SYSTEM` дополнен правилом про refs (паритет правила (8)
  primary-промпта — фильтрация при этом серверная, не prompt-trust);
- §18G.4: origin unknown + ни одной parsed-даты → `uncertainty.
  dates_unresolved` (bounded uncertainty, verdict не форсируется).

**Тесты** `tests/test_asap8_v6_p1_d10_temporal.py` (CONTRACT, 23 шт): parse
unit (meta/jsonld/rfc2822/url/мусор/будущее), enrich (failure non-fatal без
now(), success+source tag, fetch-ошибка, no-URL без fetch, бюджет 5, ID),
allowlist (invented ev-99/текст отброшен; e2e-прогон; **fallback-путь после
провала validator'а — тот же allowlist, REV-P1**; правило refs в
fallback-промпте), bounded uncertainty, repost/original в durable-записи,
pipeline жив при мусорных датах (payload содержит «published: unknown»).

## 3. D11 — Module registry completeness (v6 §C D11)

`services/module_registry.py` — решение по каждому пункту инвентаря:
| Пункт | Решение |
|---|---|
| Vision | product_module, master `flags.vision_enabled` + группы flags_module_vision/limits_vision/models_vision/keys_vision; 4 env-оси → MODULE_ENV_GATES (из rationale) |
| Temporal Factcheck | submodule `factcheck_temporal` (parent factcheck, config_tab mod_factcheck), master `temporal.tool_enabled`, группа temporal_factcheck; 3 env-оси → owner |
| Nostalgia | product_module, master `memory.nostalgia_enabled` + группа memory_nostalgia (17 ключей) |
| Dream (внутри Сон) | product_module `sleep` (карточка mod_sleep обогащается), master `memory.dream_enabled` + memory_dream; ось deep_sleep в flags_memory — владелец указан в rationale |
| Factcheck (родитель) | product_module, master `flags.factcheck_enabled` + flags_module_factcheck/limits_factcheck/prompts_factcheck |
| Embeddings/GraphRAG control plane | infrastructure spec `embeddings`: no master (сознательно), rationale называет настройки в правильных родителях (models_embeddings/keys_llm; graph-оси flags_memory/limits_graph на «Памяти», панель Embeddings); env-ось активации → owner |
| Dossier rebuild | maintenance (в rationale): operator-управление в родителе (досье-модалка), env-оси аварийные |

- PRODUCT_DEFAULTS пополнены РОВНО каноном Settings (factcheck/temporal ON;
  vision/nostalgia/dream OFF);
- analytics_anchor каждого нового spec — реальный process_id реестра
  процессов (factcheck.run, temporal.factcheck, vision.media, nostalgia.run,
  sleep.dream, embeddings.index) — телеметрия привязана к стадиям (D11.3);
- новых top-level карточек нет (id обогащают существующие; test «≤12»);
- F5 не регрессировал: гейт каждого модуля считается только по СВОЕЙ оси
  (`gate_snapshot.master_param == spec.master_param`), random-мастер цел;
- «Мёртвых ручек» нет: все мастера реально читаются runtime-гейтами
  (temporal.tool_enabled — существующий гейт; vision/nostalgia/dream —
  канон-мастера в каталоге до D11).

**Тесты** `tests/test_asap8_v6_p1_d11_registry.py` (CONTRACT, 15 шт):
инвентарь M2-паттерна (каждый пункт: spec/классификация/группы/табы),
defaults==canon, KILL_SWITCHES-покрытие полное без дублей, env-ось owned,
anchor ∈ PROCESS_REGISTRY, ≤12 top-level, F5-gate/no-regression, effective
ON/OFF/env-приоритет. Обновлён пин `test_m2_ext_f4_axes_mapped`
(Vision: rationale → owner — прямой смысл D11).

## 4. Верификация

| Прогон | Результат |
|---|---|
| Новые P1-тесты (5 файлов, 60 тестов) | 60 passed |
| dream/deep/mca_gates-hours | 173 passed |
| graphrag/factcheck | 347 passed |
| module registry/F5/mca-20/summary | 249 passed |
| Соседние (mca06 sleep, mca17, graphrag breaker/recovery/db/rebuild, scoring, memory core, perimeter) | 310 passed |
| JS-unit панелей | P1-D09-PANELS-UNIT-OK |
| JS-регрессии (dossier-guard, module-store, d07-stack) | OK |

**Итого по лейну: ~1139 passed, 0 failed.**

### Визуальные проверки (обе обязательные)

1. **Playwright детерминированный** (`tools/ui_asap8_v6_p1_d09_d11_e2e.py`,
   стабы /api, R17) → `P1-D091011-E2E-OK`: панель снов на Обзоре
   (`data-dream-panel`) с метками «отложено на следующий прогон», «дневной
   лимит», «ошибка»; подкарточка «Временная проверка» (deep-link
   `#/modules/factcheck_temporal` рендерит); карточка «Векторная память»;
   mobile 390px без горизонтального overflow; console 0 ошибок.
   Скриншоты: `plans/features/asap8-v6-remediation/evidence/
   p1_d091011_dream_panel_{desktop,mobile}.png`, `p1_d091011_modules_desktop.png`.
2. **Browser Use реальный Chrome** (тот же стаб-сервер, TMA-стаб): панель
   снов рендерится с human-метками (текст панели подтверждён js-пробой и
   скриншотом), карточки «Временная проверка»/«Векторная память»
   (`data-mod="mod_factcheck_temporal"`, `mod_embeddings`) в каталоге 21
   карточки. Скриншоты: `evidence/p1_d091011_bu_dream_panel.png`,
   `p1_d091011_bu_dream_panel_mobile.png`, `p1_d091011_bu_modules.png`,
   `p1_d091011_bu_temporal_card.png`.
   Visual Neighborhood Sweep: новых дефектов вокруг изменённых зон нет;
   sticky-save-футер «Нет изменений» виден всегда — известный headline D13
   (другой lane, не трогал).

## 5. Изменённые файлы (кандидат)

- services/dream_worker.py (D09.1, D09.2)
- services/summary_memory.py (D09.3, D09.4)
- services/temporal_factcheck.py, services/factcheck_service.py (D10)
- services/module_registry.py (D11)
- web/app.js, web/index.html (D09.5 + D11-иконка/карточки через живой реестр)
- tests: новые test_asap8_v6_p1_d09_dream.py, test_asap8_v6_p1_d09_deep_stages.py,
  test_asap8_v6_p1_d09_memory.py, test_asap8_v6_p1_d10_temporal.py,
  test_asap8_v6_p1_d11_registry.py, tests/js/asap8_v6_p1_d09_panels_test.js;
  обновлены test_dream_worker.py (пин бюджета под exactly-once),
  test_asap7_module_completeness.py (Vision rationale→owner пин),
  test_mca20_{temporal_round1044,rework1_f1_f2,integration_round1045}.py
  (autouse fetch-off + контейнер `<evidence>`)
- tools/ui_asap8_v6_p1_d09_d11_e2e.py (новый Playwright e2e)
- plans/features/asap8-v6-remediation/evidence/p1_d091011_*.png (7 шт)

## 6. Сопутствующие находки

- `related-nonblocking`: панель «Последние сны» была достижима только через
  легаси-модалку (openModuleWindow недостижим из workspace-UI) — закрыто в
  этом лейне переносом на Обзор; модалку не удалял (вне объёма).
- `unrelated/pre-existing`: sticky-save «Нет изменений» виден всегда (D13,
  headline другого lane); «Выключен» на карточке temporal в стаб-окружении —
  артефакт стаба (без сидов PG), в проде значение из каталога.
- Внешние источники не привлекались: все решения по коду/планам репозитория.

## 7. Остаточный риск

- `LIVE_UNVERIFIED` (владелец): поведение очереди отложенных групп и меток
  панелей на прод-данных (юзерские чаты с interleaved-фактами); контракт
  покрыт 60 новыми тестами на реальном SQLite + двумя визуальными прогонами.
- Отпечаток кластера = capped chronological source_ids (25): при >25 фактах
  в кластере отпечаток устойчив ровно до изменения состава первых 25 —
  принятым ограничением (совпадает с представлением дистилляции).
