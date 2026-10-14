# F2 — Direct settings (L1 Planner) + durable-аналитика (Wave 3, ASAP 7)

- Дата: 2026-10-09. База: master `71b3b69` (Wave 2); в общем дереве параллельные F7/F4 (их секции не тронуты).
- Контракт: `architecture.md` §1.6 (model slot L1), §1.10 (plan_meta durable), §8 (observability); ТЗ §18/§19;
  freeze §5.1 (SECTION-DIRECT-UI — моя), §5.2 (direct_chat_service не тронут); REV-2 non-blocking (а)/(б) закрыты.

## 1. Что сделано (file:line)

### 1.1 Каталог — `services/param_catalog.py`
- GROUPS +3: `models_direct_l1` (models, order 12, ~:217), `limits_direct_l1` (limits, 38, ~:352), `flags_direct_l1` (flags, 28, ~:448).
- `_DIRECT_L1_PG_ONLY` (~:1180) — 9 PG-only ключей (прецедент `_SUMMARY_HYBRID_PG_ONLY`): `models.direct_l1_base_url/_model_name`, `keys.direct_l1_api_key` (secret), `limits.direct_l1_{temperature,timeout_seconds,max_output_tokens,context_tokens}`, `flags.direct_l1_{enabled,fallback_enabled}`; регистрация в `_build_registry` (~:2450). НОВЫХ записей Settings НЕТ — env-фолбэк на ClassVar F1 (`DIRECT_L1_ENABLED/_CONTEXT_TOKENS=1600/_TIMEOUT_SECONDS=15/_MAX_OUTPUT_TOKENS=512`); base_url/model/key без Settings-полей → честный inherit main.
- TAB_RULES `mod_direct` in-place (~:2840): +`flags_direct_l1`/`limits_direct_l1`/`models_direct_l1` (models+keys в одной группе — прецедент Hybrid); TAB_RULES 23 без роста.

### 1.2 usage_events — `services/usage_events.py`
- `plan_meta` опциональный параметр `record()` (:112+) + `conn_insert` ($13, jsonb-строка/NULL); INSERT_SQL 12→13 параметров.
- R17-whitelist `PLAN_META_FIELDS` (:46) — те же enum-оси, что в agentic `L1_PLAN`: action/response_act/extent/tone/bucket/confidence/capabilities/tools/inherited/fallback/latency_ms/input_chars/model/source; `sanitize_plan_meta` (:96) — idents ≤64 без пробелов, числа, bool, списки idents (join ≤256), bounded 2048 байт (перелимит → честный NULL), мусор/промпты отбрасываются.

### 1.3 ΔDDL — `services/pg_db.py` + `services/database.py`
- `pg_db.py` DDL_STATEMENTS (:310+): колонка `plan_meta JSONB` в CREATE TABLE (fresh) + идемпотентный `ALTER TABLE llm_usage_events ADD COLUMN IF NOT EXISTS plan_meta JSONB` (существующие; прецедент preview_job_id :499). PG-only; SQLite не затронут.
- `database.py`: `_SCHEMA_VERSION_LLM_USAGE_PLAN_META = 35` (:1641); MigrationStep(35, "llm_usage_plan_meta_v35") в реестре; `_migrate_llm_usage_plan_meta_v35` — SQLite: guard `sqlite_master` → честный bookkeeping no-op (таблица PG-only) + `PRAGMA user_version=35`; защитный mirror-ALTER если SQLite-таблица вдруг есть. Backup-guard runner'а (VACUUM INTO + read-back, fail-closed) покрывает шаг как любую новую ступень. Итог: **v35** (Wave 1/2 были DDL=0, последняя v34 — подтверждено по реестру).

### 1.4 Durable-оси 24ч/7д — `services/execution_graph_source.py`
- `DURABLE_L1_AXES_SQL` (:1300): SQL-агрегат `WHERE module='direct_chat' AND step='l1_planner'` — calls/tokens/cost/with_meta + jsonb-гистограммы action/extent/tone/bucket, inherited/fallback-рейты, latency p50/p95 (percentile_cont по `plan_meta->>'latency_ms'`).
- `durable_l1_axes_from_row` (fail-open; calls=0 → None — честное отсутствие), `fetch_durable_l1_axes(conn, days)`.
- In-memory `response_recent_window()` остался источником live-виджета (без изменений).
- Узел «L1 Planner» карты прогона: `_l1_facts_from_events` / `_l1_planner_usage` / `_agentic_l1_planner_node` — узел `stageKey="l1_planner"`, kind=llm, первый в цепочке; метрики §18 (action/response_act/extent/tone/bucket/confidence/capabilities/**tools_resolved/tools_rejected**/inherited/fallback/model/latency). Нет события и usage-строки → узла нет (§30). Интеграция в `_build_agentic_nodes`.
- Planned-слой: `planned_nodes_from_plan` — при `plan.source=="l1"` узел PLANNER честно называется «L1 Planner» (+source добавлен в valid-оси); `_actual_facts` — l1_requested/resolved/rejected из реальных L1_PLAN/L1_CAPABILITY_REJECTED событий (REV-2 (а): F1 отдаёт resolved=() → resolved деривируется как requested − rejected; если F1 начнёт слать tools — берётся факт); сравнение TOOLS показывает «resolved: … · отклонено: …».

### 1.5 API — `web/api/analytics.py`
- `/analytics/response/summary`: `fetch_durable_l1_axes(conn, days)` (в том же conn-блоке, fail-open) → поля `l1` (всегда: shape/None) и `plan_axes` (только при with_meta>0), честный `note_ru` при отсутствии plan_meta. Пустая форма обновлена (`l1: None`). F8-регион include_prompt (:621-655) не тронут.

### 1.6 UI — `web/app.js` (только SECTION-DIRECT-UI) + `web/index.html` (Direct-регион/Pipeline)
- TABS-зеркало mod_direct (:105): +4 источника (flags/limits/models/keys — зеркало TAB_RULES).
- `directStageCards` (:10552): L1 «Планировщик (L1 Planner)» — фактический effective provider/model/source (configured слот → «Отдельный слот L1 (configured)», иначе «Наследует основную модель» + honest inherit-badge `data-effective-source`); L2 «Писатель (Verbalizer)» — основная модель, честно («отдельный слот не предусмотрен»). D-5 закрыт.
- `directL1PlannerCard()` — сводка §19 (enabled/fallback/effective source/temperature/timeout/max_output/context с подписями «по умолчанию»/«Авто»); рендер `data-direct-l1-planner` (models-вкладка).
- REV-2 (б): `directAutonomousSemantics()` + блок `data-direct-autonomous-semantics` (settings-вкладка) — requested/effective/следствие по-русски: «Выключено + L1 ON → L1 всё равно оценивает ход; при action=silent бот промолчит (без 🗿); гарантии текстового ответа нет» (семантика подтверждена кодом direct_chat_service :2109/:2418/:2438 — allowed=("REPLY",) вне allowed → тишина).
- Pipeline widget: `responseL1Rows` computed — durable-оси L1 за 24ч/7д; index.html блок `data-l1-durable-axes` (режимы 24ч/7д, скрывается при отсутствии данных); planned-узлы/сравнение рендерятся generic (L1 Planner/resolved приходят из backend planned-слоя).
- `workspaceGroupTab`: +id-маппинг `models_direct_l1 → 'models'` (keys-слот «одним домом» с моделью; прецедент Hybrid; иначе keys-категория из groupedForTab падала в 'settings').

### 1.7 Реиздан артефакт-контур (механика, прецедент F3)
- `tools/gen_param_registry_round1025.py` emit: tsv (560+header=561), screen-map, meta.md (560/149).
- Фикстуры: `tests/fixtures/round1025/catalog_baseline.json` (counts 560/120/118/23, registry_keys, group_ids, group_tab={g.id: group_tab(g.id)} вкл. content:None), `f8_baseline.json` (counts, delta 149, sha256 param_catalog.py/pg_db.py, superseded_by-пометка F2).
- Счётчики-пины «по факту» (REGISTRY 538→560, GROUPS 115→120, _TAB_BY_GROUP 113→118, v34→35, DDL 53→54, tsv 539→561, categorized 513→535, secrets 33→34, meta 538/127→560/149, L1-заголовки карточек) — 50+ файлов механическим скриптом + точечно (test_mca17c, test_frontend_tab_mapping, test_param_catalog, test_round1025_f8_registry, test_ia_inventory, test_budget_*, test_mca19, test_webapp_f5/f9, test_summary_*, test_webapp_round*/api, test_tool_coordinator, test_unified_image_request…). NON_PREFIXED += keys.direct_l1_api_key (прецедент Hybrid).

## 2. Тесты

- NEW `tests/test_asap7_direct_settings.py` — 18 passed. TEST-LIFECYCLE: CONTRACT owner=ASAP7/F2. Каталог-группа/слоты; **effective==configured** (resolve_l1_model: configured → slot "l1", пусто → inherit main); **DDL идемпотентен (прогон дважды на одной файловой БД)**; **backup-guard срабатывает до pending-шага + fail-closed** (monkeypatch migration_backup: вызов зафиксирован; провал → версия не поднята); durable-оси 24ч/7д (fixture-строки, rates/latency, рестарт-семантика: store пуст → durable полон); **usage record с plan_meta пишется/читается** (fake-pool: $13 JSON с whitelist, мусор → NULL); L1-узел build_graph (метрики/токены/первый в цепочке; legacy → узла нет); planned TOOLS resolved; widget-маркеры.
- NEW `tests/js/asap7_f2_direct_ui_test.js` — node OK (`ASAP7-F2-DIRECT-UI-OK`): honest inherit/effective, defaults, REV-2 (б) тексты (3 ветки), responseL1Rows честные «—», index-маркеры, R17 (в Direct-регионах нет include_prompt/exact-промптов).
- Соседи зелёные: сводный прогон 461 passed (mca17c, f8_registry, frontend_tab_mapping, param_catalog, ia_inventory, pg_db, budget_guardrails, token_analytics, mca11, agentic_events, execution_graph, asap7_*) + 328 passed (prompt_migrations, direct_chat, outgoing_guard, llm_react, tool_calling, decision-семейство) + сотни в батчах webapp_*/summary_* (см. прогоны ниже). `py_compile` всех затронутых — OK; `node --check web/app.js` — OK. Полный pytest не запускался (правило лейна).

## 3. Визуальная верификация (обязательные обе)

- **Playwright** (scratch `Temp\opencode\f2_visual_e2e.py`, мок-сервер из tools/ui_round1025_matrix.py + F2-стабы /api/analytics/*): 28/28 checks green на **desktop 1280×800 и mobile 390×844** — карточки L1/L2 с effective-source, сводка L1 Planner, autonomous-semantics (честный текст), Pipeline «Последний ответ» (PLANNER·L1 Planner + resolved/rejected в «План → Факт»), 24ч durable-оси с распределениями, 0 pageerror, 0 горизонтального overflow. Скриншоты: `OPENCODE_WORKFLOW_SCRATCH\f2_shots\` (8 шт.).
- **Browser Use** (реальный рендер Chrome, мок-сервер с серверными /api-стабами): models-вкладка — 2 карточки, `[data-l1-effective]` = «L1 Planner: planner-x · https://l1.example/v1», enabled «включён»; settings — семантика-блок с точным honest-текстом; oversight/summary — 24ч `[data-l1-durable-axes]` present, «Последний ответ» — L1-title-ok|resolved-ok. Скриншоты сняты.
- Visual Neighborhood Sweep: в изменённых областях посторонних дефектов не видно; модульный бейдж «Включён, но не работает» — существующее поведение F3-гейта мок-стаба (не мой регион).

## 4. REV-2 non-blocking — статус

- (а) `L1_PLAN.resolved` всегда пуст: **виджет-часть закрыта** — resolved деривируется в моём слое (requested − L1_CAPABILITY_REJECTED; с переходом на факт F1 `tools`, когда появится). Эмиссия в F1-регионе (`direct_chat_service._plan_direct_l1` :3538 `resolved=()`) — замороженная зона F1; точечный фикс (передавать `resolved` из `_l1_tool_subset`) — один аргумент на стыке, оставлен владельцу F1-региона/Orchestrator (не блокер UI: деривация честна).
- (б) autonomous-семантика — закрыта в UI (requested/effective/следствие, человекочитаемо).

## 5. Остаточный риск / заметки

- **plan_meta в primary path пока никто не пишет**: F2 по контракту дала `record(plan_meta=…)` + читатель; точки записи — `direct_chat_service` (dedicated-слот :3498 и llm.generate путь) — зона freeze F1. До одного-строчного дополнения call-site durable-оси честно пусты (`available=false`, UI показывает «Свежие прогоны»). Рекомендация Orchestrator'у: F1-region follow-up (передать sanitize-ready dict из l1_meta/plan при usage-записи).
- Параллельные лейны в общем дереве: финальные счётчики сниманы по факту дерева (REGISTRY 560 = 538+9 F2+13 F4; GROUPS 120 = 115+3 F2+2 F4). Лейн, приземляющийся последним, — ребейзер одного sed; sha256-пины f8_baseline зафиксированы на текущем снимке.
- LIVE_UNVERIFIED (owner gate): прод-агрегаты 24ч/7д и виджет на реальном трафике — после деплоя Wave 3 (наблюдаемость готова).
- Pre-existing RED на чистом HEAD (вне лейна, воспроизведено stash-прогоном): 4 direct-теста (concurrency/image_generation×2/payload_builder), 6 исторических version-пинов (webapp_f7/f9/hotfix7-10, f11 — ждут 2.58.71), tool_loop. НЕ мои, в отчёт Orchestrator'у.
- Сосед-шов F7: `test_tool_coordinator/ test_unified_image_request ::forbidden_paths_out_of_diff` (diff-allowlist web/) падают на `web/api/summary_test.py`/`cover_styles.py` F7 — их лейн обязан дополнить allowlist; мои web-файлы (analytics.py/app.js/index.html) в allowlist входят.

## 6. Прогоны (финал)

- `test_asap7_direct_settings.py` 18 passed; node-харнесс OK.
- Сводный инвариантный прогон **461 passed**; direct/prompt-семейство **328 passed**; webapp/summary-батчи **653 passed** (2 FAIL = pre-existing version-пин + F7-шов); budget/decision/summary-батчи **535+216 passed** после пинов; mca19 10 passed.
- Откат лейна: cold git revert моих файлов; soft: каталог-ключи пусты → inherit main (байт-паритет с Wave 2), v35-колонка инертна (старый код не читает), `flags.direct_l1_enabled=false`/env `DIRECT_L1_ENABLED=false` — прежний pipeline.
