# ASAP 8 v6 — Ledger D01–D14 (Phase 0 reconcile, read-only)

Baseline: master `1e980275ce5c857b825860b50a34a2486c790359` (release 2.58.77), verified 13.10.2026.
Sources: v6 `plans/ASAP8_v6_delta_after_F1-F9.md` §C; v5 `plans/current_task.md` §18A–§18I (line refs in-file);
`plans/features/asap8-reliability-truthfulness/architecture.md` (F1–F9 scope). All code claims re-checked by
grep/read on HEAD 1e98027, not from memory. F1–F9 touched NONE of D01–D14 except fragments noted (F5 → D08/D11).

---

### D01 P0 — Dossier/settings stale-response races (v5 §18A)
source: v6 §C D01 + v5 §18A.1–18A.2
code path:
- Settings half — IMPLEMENTED (F0-контракт раундов 10.20–10.25): `web/app.js::persistItems` :13394–13560 —
  epoch снимок до await (:13466), `inScope(epoch)`-гвард после await (:13479, устаревший ответ не мутирует UI),
  optimistic `updated_at` в payload (:13467–13471), draft-восстановление при 409 (:13505–13533);
  `saveModalEdits` снимает dirty-снапшот до await (:8029–8030); сервер — optimistic 409 на
  `updated_at` chat_params (`web/api/routes.py::post_config` :608–680). Module toggle: scope+epoch fix до await
  (`setModuleState` :9653–9666).
- Dossier half — ABSENT: `loadDossier` (:8124–8135) применяет ответ безусловно после await (нет
  request_token/instance-гварда: `this.dossierData = data` без проверки, что открыт тот же
  chat/participant/инстанс); `saveDossier` (:8147–8170) строит URL из мутабельного `this.activeChatId`/
  `dossierUserId` на момент клика, ответ применяется безусловно; `startDossierRebuild`/`pollDossierRebuild`
  (:8206–8290) — тот же паттерн без токена. Grep `request_token` в web/app.js — 0 совпадений.
runtime path: да — обе половины живут в прод-MiniApp (досье-модалка «Участники», sticky-save конфига).
ui path: досье-модалка (index.html :8110–8115 footer), sticky-save, тосты сохранения.
existing tests: settings — JS unit на реальном контракте epoch/stale: `tests/js/round1025_save_state_test.js`
(«устаревший scopeEpoch → ответ игнорируется»), `round1025_scope_selector_test.js`,
`round1025_f4_module_store_test.js` (f: stale-ответ не меняет чужой scope), `routing_test.js` (D2). Всё —
JS-unit с fake-ctx (для UI-гонки это корректный seam), real-storage E2E нет. Dossier — тестов гонки НЕТ.
missing proof / missing implementation: 1) dossier request_token/instance-guard на load/save/rebuild;
2) save-подтверждение не называет цель («Изменения сохранены (N)» :8098 вместо «Saved for <chat>»/глобально);
3) негативный сценарий delay A→B для досье (load/rebuild) в тестах отсутствует; для settings —
acceptance «slow preflight + switch» покрыт JS-unit косвенно, явного теста сохранения-в-полёте при
switch нет (есть на loadConfig/routing).
verdict: PARTIAL
next action: backend+UI, размер S: dossier request_token+instance-гварды (load/save/rebuild-poll),
scope-именованные тосты, 2–3 негативных JS/E2E теста (A→B delay, switch во время save, rebuild-поллинг).

---

### D02 P0 — group→supergroup migration (v5 §18B)
source: v6 §C D02 + v5 §18B.1–18B.2
code path: `handlers/chat_lifecycle.py::on_chat_migrated` :209–274 (ASAP7 F5/C9): `_store.add_link(old, new)`
(:243) ЗАТЕМ `_store.migrate_profile` (:244). `services/chat_lore_store.py::migrate_profile` :744–803:
первым делом `resolved_old = _resolve_on(conn, old_chat_id)` (:754) — по chat_links; т.к. add_link УЖЕ
записал old→new, `resolved_old == new_chat_id` → early return `{"moved": False, "merged": False}` (:755–756)
ДО чтения старого профиля. Далее handler видит `get_profile(new) is None` (профиль лежит под old) →
создаёт ПУСТОЙ профиль `upsert_profile_on_join(new)` (:256–258). Итог: профиль не переносится и не
мерджится, старые данные осирачиваются (читаются только через link-resolve), merge-ветка Q9 (:778–797)
в реальном флоу недостижима. Это в точности v5 §18B.1 — НЕ исправлено.
Матрица миграции: переносятся только `chat_profiles` (cols :757) + `chat_admins` (MOVE/COPY_ADMINS_SQL
:137–145) + history remap. feature opt-ins, keys/provider bindings, lore/memory FK, module state,
dossier/persona-ownership — НЕ мигрируют. Роль-эскалация из §18B.2 неприменима в текущей схеме
(chat_admins без role-колонки), но матрица неполна.
runtime path: да — регистрируется в bot.py до широких message-роутеров; событие `migrate_to_chat_id`.
Дополнительно `message_identity.register_chat_id_migration` (:222–240) — SQLite-осidentity (MCA-03), отдельный seam.
ui path: нет (Telegram-событие).
existing tests: `tests/test_asap7_chat_lifecycle.py` (FakeStore с ручными
ensure/get_profile/add_link/migrate_profile — самостоятельно «притворяется» успехом), `tests/test_chat_lifecycle.py`
(mock `_lifecycle_store`), `tests/test_chat_lore_store.py` :856–1004 (migrate_profile — `_FakeConn`/`_FakePool`,
in-memory эмуляция asyncpg; тесты зовут migrate_profile БЕЗ предзаписанного link — skip-ветка не воспроизводится).
REAL-storage теста (реальный handler + реальный PG store) НЕТ — прямое нарушение §18J/v5 acceptance.
missing proof / missing implementation: атомарная/idempotent связка link+profile (или перенос вызова
add_link после migrate), duplicate-event и partial-failure retry поведение, полная матрица миграции,
real-storage тест с injected failure.
verdict: FAILED
next action: backend, размер M: переупорядочить/объединить link+migrate (идемпотентно), минимум — матрица
profile+admins+gates/keys-перечень с решениями, real-storage тест: duplicate event + сбой посередине.

---

### D03 P0 — Direct L1 credentials/accounting/temperature (v5 §18C.1/§18C.6)
source: v6 §C D03 + v5 §18C.1, §18C.6
code path: `_plan_direct_l1` (`services/direct_chat_service.py` :3500–3655). Dedicated-ветка:
`_l1.dedicated_generate(self.llm, messages, slot, ...)` :3520–3523 → `services/direct_l1.py::dedicated_generate`
:428–465 → `llm._post(..., api_key=slot.api_key, base_url=slot.base_url)` :442–444. Политика
ключей/бюджета живёт в `services/llm_client.py::_resolve_api_key_and_source` :439–501 (own chat key →
global forbidden → NoApiKeyForChat('budget')); на dedicated-пути она НЕ вызывается (ключ передан явно) —
гэп v5 §18C.1 подтверждён на HEAD.
Учёт: первая попытка dedicated пишет usage-row вручную (:3595–3606, `usage_events.record`, step="l1_planner");
repair-попытка :3618–3621 присваивает `usage2` и НИГДЕ не записывает — попытка ремонта не учтена.
Temperature: `l1_temperature()` (direct_l1.py:379–389) применяется ТОЛЬКО на main-пути (`llm.generate`
:3527); payload dedicated_generate :439–441 = model+messages+max_tokens, temperature отсутствует —
§18C.6 «сохранена, но не применяется» подтверждён. UI configured-vs-applied: `_attach_l1_plan_meta`
(:3657+) пишет plan_meta на usage-строку (source/inherited/fallback), но температуры configured-vs-applied там нет.
runtime path: да — при непустом `models.direct_l1_*`/`keys.direct_l1_api_key` slot.dedicated=True.
ui path: нет прямого (Inspector-полей configured-vs-applied L1 нет).
existing tests: dedicated key/budget policy — тестов НЕТ (grep `dedicated_generate|resolve_l1_model|direct_l1_api_key`
в tests → 0); repair-usage тестов нет; temperature тестов нет. Есть общие L1 unit-тесты ASAP7
(test_direct_llm_decision_asap32 и др.) — не на эти seam'ы. All FakeStore-level.
missing proof / missing implementation: 1) пропускать dedicated через тот же resolver/budget (или явный
эквивалент) с 4 кейсами §18C.1 (no own key + global forbidden; exhausted; own key; invalid→repair учтён);
2) запись usage2; 3) temperature applied либо честный unsupported + Inspector.
verdict: PARTIAL
next action: backend, размер M (ядерная часть — авторизация+accounting; температура и Inspector — хвост S).
D03 и D04 шарят Direct-контракты — merge в один Direct-лейн перед общими тестами (v6 phasing).

---

### D04 P0 — Direct planner/tools/evidence/window (v5 §18C.2–5/7–8)
source: v6 §C D04 + v5 §18C.2–18C.5, §18C.7–18C.8
code path: execution modes — ABSENT: grep `execution_mode|simple_tools|adaptive_tool_chain|tool_orchestrat`
в direct_chat_service.py/direct_l1.py → 0 совпадений. Топология §18C.7 (L1 выбирает режим, bounded
orchestrator) не существует. Evidence packer: `direct_l1.py::build_evidence_packet` :580–619 — конкатенация
tool_context + глобальная обрезка `packet[:cap]`, cap=4000 (`DIRECT_L1_EVIDENCE_MAX_CHARS` :76/:574) —
first-source domination §18C.2 воспроизведён в коде как есть (нет per-source reservation, нет различия
«tool succeeded» vs «evidence delivered»). L1 trim: `_cap_context` :523–543 — структурные секции с
бюджетами (не слепая голова) — частично закрывает §18C.5; проверка финального пакета реальным
tokenizer'ом и резерв под хвост вопроса — не видна. L2 под фактическое fallback-окно: recompose на
уровне llm_client (§45, упоминается :1477) — частично; пересборка L2-пакета под fallback-модель с
protected-блоками на уровне пакета — нет. Planner-fallback capability resolver §18C.3: детерминированный
fallback без capabilities существует (deterministic fallback :3635–3639), безопасного resolver/честного
decline с `planner_fallback_reason`/`required_capability` — не найдено. Observability §18C.8: L1_PLAN
событие + usage-строки есть; executor/orchestrator/follow-up метрик нет (нечего мерить — оркестратора нет).
runtime path: n/a (основное отсутствует); существующая часть (L1→tools→evidence→L2, single mode) живая.
ui path: нет.
existing tests: build_evidence_packet — dedicated unit-тестов НЕТ (grep в tests → 0); L1 planner/repair
покрыт ASAP7 unit-тестами (FakeStore-level). Матрица §18C.9 отсутствует.
missing proof / missing implementation: почти весь slice: execution modes + orchestrator + evidence
packer с fair allocation + L2-window rebuild + capability fallback + failure matrix + автоматические
gates (human gate запрещён).
verdict: PARTIAL (ядро §18C.7/§18C.2 — ABSENT)
next action: backend, размер L. Самый большой остаток в D-блоке; делить на подслайсы: (1) execution_mode
в L1Plan + simple/none пути; (2) evidence packer; (3) orchestrator+budgets; (4) failure-matrix tests.

---

### D05 P1 — Experience hybrid detector / lifecycle / usefulness (v5 §9, §18E)
source: v6 §C D05 + v5 §18E.1–18E.7
code path: пайплайн существует: `services/mca_experience_jobs.py` (capture-cursor → propose → validate →
activate/suspend → outcome-link → prune; header :14; `_checkpoint` :404; cursor inherit :381–402;
`_capture_feedback` :482 читает таблицу feedback по cursor; `_capture_tool_events` :527; review-джобы).
`services/mca_experience.py::record_feedback` :1610 (+ `enqueue_on_correction` :1659). F5 (§5.4):
worker глобальный, per-chat opt-in (`learning_enabled_for_chat` :134). ПРОДАКШЕН-ВХОД: grep
`record_feedback\(|enqueue_on_correction\(` по не-тестовому коду → только определение и внутренний вызов;
handlers/ — 0 совпадений. Semantic detector обычного чата (18E.1 «Hybrid production feedback entry») —
ABSENT: candidate'ы появляются только из ручных/тестовых записей feedback.
Sub-фиксы 18E.2–18E.6 (cursor-after-durable, uniqueness по subject, concrete preference, resume incomplete,
fair scan) — частично представлены механизмом checkpoint/cursor/uniqueness, но точечно не верифицированы
в этом прогоне; 18E.7 UI-воронка «Заметил→Урок→Проверил→Применил→Помогло» — есть status-лента
data-experience (module_registry :164), полной воронки с usefulness=known/(pos+neg) и sample — не найдено.
runtime path: job-инфраструктура живая (enqueue_experience_review, tick); прод-источник кандидатов отсутствует.
ui path: «Опыт и уроки» submodule-карточка (F5); воронка полезности — нет.
existing tests: `tests/test_mca16_experience_block_{a,b,d,f}_round1039.py` — обширные unit-тесты сервиса
(рiceка record_feedback/кандидаты/исходы); storage — in-memory/sqlite-fixtures уровня сервиса, не
PG-integration. Продакшен-entry тестов нет (нечего тестировать).
missing proof / missing implementation: главный остаток — semantic detector + запись feedback из живого
чата (candidate ≠ truth), затем построчная верификация 18E.2–18E.6 на реальном хранении и UI-воронка.
verdict: PARTIAL
next action: backend, размер L (детектор + entry) c предварительной investigation-пробой M (сверить
E.2–E.6 по коду на реальном storage seam; возможно, часть уже закрыта).

---

### D06 P0 — Hard chat isolation across cognition (v5 §9A, §18F.4)
source: v6 §C D06 + v5 §9A/U13, §18F.4
code path: механизм «глобальный top-K, потом фильтр chat_id в Python» подтверждён на HEAD:
- `_search_archive_knn` (`services/summary_memory.py` :2751–2814): комментарий :2752–2753 прямо признаёт
  «KNN top-k выполняется отдельно, фильтр chat_id … в Python». int8: k=limit×4 глобально → фильтр (:2769);
  float: k=limit РОВНО → фильтр (:2805) — чужие чаты могут занять весь K → false-empty. Overfetch ×4 —
  не partition и не «proven staged strategy».
- Граф-факты: `_vec_candidates`/`_vec_int8_rows`/`_vec_float_rows` :4157–4202 — глобальный KNN (k=fetch_k×4 / ×2)
  → `_filter_vec_rows` по chat_id в Python (:4204–4213).
- Дедуп: `_dedup_knn` :3342–3354 — k=3 ГЛОБАЛЬНО → фильтр в Python — в точности v5-риск «dedup с очень
  малым K».
Остальная изоляция (память/Stories/Experience/dossier/Initiative) — per-chat по схеме БД (chat_id в
таблицах), дефолтный partition `chat_id` соблюдён конструктивно; cross-chat capability default-OFF.
Специфических SQL/vector/prompt-утечек «два чата с одним user_id» — тестов нет.
runtime path: да — все retrieval-пути живые (Summary, GraphRAG RAG, dedup).
ui path: нет.
existing tests: dedicated тестов на chat-scope векторного поиска НЕТ (grep `_search_archive_knn|vector_search|_dedup_knn`
в tests → 0); изоляция покрывается косвенно per-chat схемами.
missing proof / missing implementation: scope-before-top-K (per-chat partition/namespace в vec-таблицах
либо доказанный staged overfetch), кейс float k=limit, dedup k=3, negative-тесты «чужой чат заполняет K».
verdict: FAILED (§18F.4-механизм в точности присутствует)
next action: backend, размер M: пер-чатный scope до KNN (vec0 — metadata-filter/partition или
per-chat virtual table), тесты archive/graph/dedup на cross-chat заполнение K.

---

### D07 P0 — Persistent overrides + badges (v5 §9B, U11/U12)
source: v6 §C D07 + v5 §9B/U11/U12
code path: data-модель существует: `web/api/routes.py::get_config` отдаёт per item: эффективный `value`,
`chat_source` ('chat'|''), `global_value` (:513–574); глобальная запись идёт в глобальные строки только
(`_post_config_global`), per-chat override — chat_params (`post_config` :608+), DELETE override —
`/api/config/chat/{key}` :964. UI: `itemOverriddenByChat` (:7621), `configSourceLabel` (:7628),
`configItemNotice` «локально включено при глобально выключено» (:7647), `resetChatOverride`
«Вернуть глобальные» с RBAC-паритетом (:7659–7687). Module master OFF не затирает stored chat override
(F0 overlay, configItems не мутируются — :9661–9663).
ОТСУТСТВУЕТ: global-view avatar stack/popover со списком переопределивших чатов + quick «Открыть чат»
(эндпоинта «какие чаты переопределили ключ» нет); bulk-действие с подтверждением затронутых чатов;
D01-гонки применительно к badge/action (resetChatOverride без epoch-гварда).
runtime path: да (конфиг-читатель/писатель живые).
ui path: карточки параметров (chat scope), кнопка «Вернуть глобальные».
existing tests: `round1025_*` JS suite (module store/state/override semantics — hasOverride и т.п.),
webapp unit; JS/unit FakeStore-level; реального storage-теста «global save не трогает explicit override»
в явном виде не найдено.
missing proof / missing implementation: overrides-map API + global popover, bulk confirm, гонки на action.
verdict: PARTIAL
next action: backend+UI, размер M: (S) endpoint override-map + (M) popover/bulk в UI; Freeze resolver/schema
перед UI (v6 phasing).

---

### D08 P0 — Random/Quantum full module + broken toggle (v5 §10/§10.5)
source: v6 §C D08 + v5 §10, §10.5, M7/M8/U5/U12
code path — ТОЧНЫЙ код-путь ошибки владельца (не догадка):
1. F5 добавил PG-only ParamSpec `memory.random_enabled` БЕЗ Settings-поля
   (`services/param_catalog.py` :2731–2741, group=memory_random) + master_param в module_registry
   (`services/module_registry.py` :188) + PRODUCT_DEFAULTS :223–242 (только effective-логика, НЕ сидирование).
2. `services/config_cache.py::get_all` :477–493 = строки bot_settings + `_synthetic_group_items` :495–523,
   который синтезирует ТОЛЬКО группы из `_SYNTHETIC_SECRET_GROUPS` (keys_random) и даже там ключи без
   settings_field пропускает (:517–521). `memory.random_enabled` строк в bot_settings не имеет
   (pg_db._seed_settings сеет только Settings-канонические ключи) → в снапшоте отсутствует.
3. `GET /api/config` строит items ТОЛЬКО из `cache.get_all()` (`web/api/routes.py` :488–494) →
   ключа в `configItems` нет.
4. Карточка Random: toggle → `setModuleState` → `_moduleConfigItem(m)` → null →
   toast «Параметр недоступен: memory.random_enabled» (`web/app.js` :9643–9646).
   Дедлок: владелец не может включить/выключить мастер из UI вообще (рантайм `mca_gates.py` :1160–1169
   честно читает hot с default True, но UI-управление недостижимо, пока строка не появится в bot_settings).
Остаток модуля: `memory.random_uses_*` PG-only применения (MCA-10b) — ParamSpec есть; consumer registry
(purpose/required/fallback/latency), source health/buffer/last batch, унифицированный
`get_random/get_int/choice/sample` — в полном объёме §10.5 не найдено (частично есть mca_random-инфраструктура
MCA-10a/b; точечная верификация не входила в прогон).
runtime path: да — гейт живой, применения живые; UI-мастер сломан (см. выше).
ui path: карточка «Случайность» (Modules) + настройки memory_random.
existing tests: `tests/test_asap8_f5_module_truth.py` (M7: master_param/default/registry — FakeStore-level,
проходят, потому что проверяют каталог/registry, а не GET /api/config), `test_asap7_module_completeness.py`
:225–238/:290, `test_mca10b_random_applications_*`. Теста на «ключ без строки bot_settings виден в
/api/config» НЕТ — потому баг и прошёл.
missing proof / missing implementation: (1) render PG-only ключей в /api/config с честным дефолтом
(синтетика для memory_random аналогично keys_random, либо startup-seed строки), (2) регресс-тест
«PG-only ParamSpec → присутствует в /api/config», (3) остаток §10.5 (registry/health) — отдельная задача.
verdict: FAILED (владельческий симптом воспроизводим из кода; точный root cause найден)
next action: backend, размер S на фикс тумблера (+S тест); остаток D08 (consumer registry/health) — M, отдельным slice.

---

### D09 P1 — Dream/Deep Sleep/freshness/GraphRAG continuity (v5 §18F)
source: v6 §C D09 + v5 §18F.1–18F.6
code path: `services/dream_worker.py` + `memory_maintenance.py`.
- 18F.1 (dream batch limit): watermark двигается ТОЛЬКО по успеху полного тик-батча (:44, :802–803,
  :1016–1027 «водяной знак — НЕ мимо упавшего кластера»), skipped-кластеры логируются со статусами
  (window_skip/budget_skip :944–965, :1143–1151). По коду вечный skip исключён; отдельного
  deferred-queue нет — policy «переехают в следующий тик».
- 18F.2 (00:00→7): НЕ исправлено — `dream_worker.py` :1680–1682:
  `target = int(await resolve_setting_cached("memory.deep_sleep_hour", ...) or 7)` — 0 подменяется на 7.
  (Аналогичное чтение в mca_gates :1758–1784 — проверить при фиксе.)
- 18F.3 (broad memory freshness по version/range): идентичность по count — точечно не верифицировано;
  инвариантов «freshness по source-range/version» не найдено (вероятно ABSENT).
- 18F.5 (GraphRAG outcomes): единого исхода run'а (no_new_facts/all_duplicates/success/partial/
  text_only_vector_deferred/write_failed) нет; встречаются `all_duplicates` в trace (dream :2276,
  persona :2668), `write_failed` reason в consolidate (memory_maintenance :1187), batch.text_only
  счётчик (`_save_graph_fact_embedding` :3356+) — разрозненно, не как контракт.
- 18F.6 (stage truth Deep Sleep): статусы skip/error/duplicate/unchanged различаются (:2091–2152,
  `_log_deep_skip` :2418), «no new insight» как нейтральный ok — есть (unchanged); формального
  разделения model-call-ok/validated/persisted — нет.
- Панели last tick/run IDs/reasons: memory_dream_log + trace_deep существуют; UI-панели сна — частично
  (Status «Сон и активность»).
runtime path: да — dream/deep_sleep джобы живые.
ui path: Status «Сон и активность», memory-панели.
existing tests: dream/deep_sleep covered ASAP7-тестами (FakeStore/unit, косяются вокруг watermark/статусов);
тестов на 00:00 НЕТ (иначе бы падали), на GraphRAG outcome-модель нет.
missing proof / missing implementation: фикс `or 7` (+тесты 00:00/01:00/23:00/missing, timezone в UI);
freshness-идентичность; outcome-модель GraphRAG; stage-разделение deep.
verdict: PARTIAL (с подтверждённым живым дефектом `or 7`)
next action: backend, размер S (0-vs-None + тесты) отдельным срочным slice; остальное — M (outcome enum
+ freshness investigation).

---

### D10 P1 — Temporal factcheck evidence integrity (v5 §18G)
source: v6 §C D10 + v5 §18G.1–18G.5
code path: `services/temporal_factcheck.py` — дата-модель ЕСТЬ: `repost_received_at`,
`original_published_at` (+precision), `date_source`, `retrieved_at`, `published_at_source`
(:114–158, :426–484); telegram-origin даты извлекаются (telegram_origin/telegram_message :426–440);
для web-evidence `published_at: None` честно-unknown, попытки fetch/parse даты публикации НЕТ
(:871–886, «published_at честно unknown (извлечение даты …)») → `date_parse_failed` reason_code
отсутствует за неимением parse-attempt. evidence_refs валидируются по payload (:663–674) —
18G.3 частично. Verdict-модель с temporal sufficiency/dated counts (:728–795) — частично.
UI/аналитика source chain (18G.5 Run Card) — нет (Run Card отсутствует как примитив, см. D12).
runtime path: temporal factcheck живой (mca-20).
ui path: карточки factcheck; date-колонок source/repost/original в UI не найдено.
existing tests: mca-20 тесты существуют (test suite temporal factcheck, FakeStore/unit уровень).
missing proof / missing implementation: fetch/parse attempt для web-дат + `date_parse_failed`
(не-фатально, без подстановки now()); UI-видимость дат/parse-status; негативные тесты
(invented IDs/repost chain/missing date).
verdict: PARTIAL
next action: backend, размер M (парсер дат публикации + reason codes), либо явное owner-исключение
«честный unknown для web» — тогда S (документирование + тест честного unknown).

---

### D11 P0/P1 — Module registry completeness (v5 §8/§17)
source: v6 §C D11 + v5 §8, §17
code path: `services/module_registry.py` — 5 ModuleSpec: initiative (:75), stories (:101),
character (:125), experience (:152), random (:181). D11-инвентарь НЕ покрыт registry: Vision,
Factcheck, Nostalgia, Dream, dossier maintenance, GraphRAG/Embeddings, autonomous workers — как
ModuleSpec'ы не зарегистрированы (часть живёт как env-оси MODULE_ENV_GATES/отдельные панели —
Embeddings-панель есть, factcheck runtime-гейт есть). «100 meaningless cards» — не нарушено;
fake parentGate снят F5 (проверено: `_moduleRuntimeReason`, reasons chat_off/global_off/env_off/
provider_unavailable/parent_off — app.js :9441–9520). Telemetry labels started/attempted/invalid/
fallback/persisted/published — частично (Summary attempted_invalid есть F1; остальное точечно).
runtime path: registry_for_frontend в /api/config (routes.py :590–594).
ui path: Modules-витрина.
existing tests: test_asap8_f5_module_truth.py (M1–M3/M6/M7), test_asap7_module_completeness.py
(пин обновлён F5). FakeStore/unit.
missing proof / missing implementation: решение по каждому из 7 незарегистрированных элементов
(ModuleSpec с master/effective/provenance ЛИБО явное owner-исключение), сверка telemetry-labels.
verdict: PARTIAL
next action: investigation, размер S→M: таблица инвентаря с решением на каждый пункт (без строителя),
затем M на реализацию выбранных ModuleSpec.

---

### D12 P1 — Status/Analytics truthful data model + widgets (v5 §18I)
source: v6 §C D12 + v5 §18I.1–18I.12
code path: фундамент есть: durable events (mca_events, pipeline_events, SUMMARY_L2_STAGE и т.п.),
Initiative funnel (F6, `status_service.intent_snapshot` :741–856), pipeline Run Inspector + latest
(F4, /api/analytics/pipeline/runs/latest), Summary coverage-оси (F1), Embeddings health (F8),
Сердцебиение EKG (index.html :6562–6619), «Сон и активность» (:6768).
ОТСУТСТВУЕТ (перечень §18I.10–18I.12): единая durable machine-семантика
(queued→started→completed→validated→persisted→delivered + degraded/fallback/blocked/retry);
time-range статистика из durable events; Unified Run Card (run ID/scope/stage/outcome/latency/
tokens/cost/evidence counts/fallback/links); Status-секции Life Stream/Memory Cycle/Learning/
Availability; Analytics-табы (pipeline waterfalls, outcomes, durable heatmap, dependency, Summary
coverage, temporal source timeline, overrides map); tooltips/accessibility/drill-down.
runtime path: существующие статус-эндпоинты живые; нового data-model нет.
ui path: Status + Analytics страницы (текущие, не редизайн).
existing tests: webapp_f6/pipeline analytics тесты (118/45 по F4-коммиту), JS unit. Всё unit/FakeStore;
визуальная часть не тестируется по определению.
missing proof / missing implementation: весь data-first слой + редизайн. По v6 phasing — ПОСЛЕДНИЙ.
verdict: PARTIAL (редизайн ABSENT, фундамент есть)
next action: backend+UI, размер L. Сначала data-semantics (backend M), затем widgets (UI L).

---

### D13 P0 — Universal save contract + mobile shell (v5 §18I.4/13/14)
source: v6 §C D13 + v5 §18I.4, §18I.13, §18I.14
code path:
- Постоянный нижний Save-футер ЕСТЬ: компонент `sticky-save` (`web/app.js` :18062–18117) рендерится
  ВСЕГДА — на clean показывает «Нет изменений» с задизейбленными кнопками; размещён в index.html
  :3336 (конфиг-вкладки), :5921, :3728 и :8113 (модалки; там footer.modal-actions — отдельная нижняя
  область, тоже постоянная). v5-контракт «clean → no Save bar; dirty → компактный Save в top header;
  no full-width fixed footer» — НЕ выполнен.
- Мобильная нижняя навигация ЕСТЬ: `bottom-nav` <768 + `more-sheet` (index.html :7905–7926,
  комментарий :72 «<768 — bottom-nav») — решение владельца «убрать bottom nav» НЕ выполнено.
- Механика автосохранения/отката/черновиков — есть: toggle/select мгновенный autosave по server-ack
  (F0, `saveConfigItem` :13562+, module optimistic+rollback :9653–9700), dirty-count (:4337), failed-
  подсветка (:18095–18096), 409 draft-восстановление (:13517–13532), scope-гварды (D01).
- Leaving-dirty защита (draft preserve on route change) — точечно не найдена (route switch делает
  loadConfig; черновик полей неявно теряется).
runtime path: n/a (UI).
ui path: все конфиг-вкладки/модалки + mobile shell.
existing tests: `round1025_save_state_test.js`, `round1025_f4_module_store_test.js`,
`round1020_ui*_test.js` (menu-пины, вкладки), Playwright smoke (в F-отчётах). Все — unit/screenshot
уровень; acceptance-матрицы desktop/portrait/landscape + 4xx/5xx/rapid-toggle нет.
missing proof / missing implementation: убрать постоянный sticky-save (dirty-only, top-header compact),
убрать bottom-nav/more-sheet в пользу компактной верхней навигации, leaving-dirty protect,
route-inventory + acceptance-матрица.
verdict: PARTIAL (механика есть; два headline-решения §18I.13/14 не реализованы)
next action: UI, размер M (save-contract) + M (mobile shell); v6 phasing — UI last, после D12 data.

---

### D14 P1 — Help and final reconciliation (v5 §§25–31)
source: v6 §C D14 + v5 §§25–31
code path: Help существует как страница «Справка» (index.html :7759–7779, T-2400) + intelligence-guide
seed (`config_cache._seed_intelligence_guide`, code-canon из seed-файла) + help_anchor в ModuleSpec.
Синхронизация Help ↔ фактический runtime — не выполнялась для v6 (F10 не закрыт: только test-pin
коммиты `3f5b912`, `855a3e5`).
`plans/runtime_task.md` — STALE подтверждён: описывает baseline 0c4f3a5/2.58.74 и «F1 в работе»,
фактический HEAD 1e98027/2.58.77 с F1–F9 закоммиченными. `plans/workflow_state.md` — аналогично
(констатация v6 header; детали не проверялись в этом прогоне). Финального отчёта
implemented/tested/committed/deployed/live-verified по каждому C/D ID — НЕТ.
runtime path: n/a.
ui path: Справка.
existing tests: n/a (документационный ID).
missing proof / missing implementation: актуализация workflow_state/runtime_task (agent-owned), Help
по фактическому runtime, финальный owner-report с покрытием всех ID и live-evidence; запрет P0 в backlog.
verdict: ABSENT
next action: investigation/report, размер L по трудоёмкости, но строго ПОСЛЕДНИЙ (после ремедиации
D01–D13 и C-остатков); механика — S на файлы, содержание — производное от остальных ID.

---

## Сводная таблица

| ID | Вердикт | Остаток | Размер |
|---|---|---|---|
| D01 | PARTIAL | dossier token/guard, scope-named toast, E2E | S |
| D02 | FAILED | link-before-migrate skip подтверждён; real-storage тест | M |
| D03 | PARTIAL | dedicated L1 мимо key/budget; usage2; temperature | M |
| D04 | PARTIAL (ядро ABSENT) | execution modes/orchestrator/evidence/window | L |
| D05 | PARTIAL | прод-детектор entry; E.2–E.6 верификация; воронка | L (investigation M) |
| D06 | FAILED | scope-before-topK (archive/graph/dedup) | M |
| D07 | PARTIAL | overrides-map popover, bulk, action-гонки | M |
| D08 | FAILED | /api/config не рендерит PG-only ключ (root cause найден) | S (+M остаток §10.5) |
| D09 | PARTIAL | `or 7` жив; GraphRAG outcome enum; freshness | S срочный + M |
| D10 | PARTIAL | web date parse attempt + date_parse_failed | M (или S при owner-исключении) |
| D11 | PARTIAL | 7 элементов вне registry — инвентарь-решения | S→M |
| D12 | PARTIAL | data-semantics + редизайн | L (UI last) |
| D13 | PARTIAL | постоянный sticky-save + bottom-nav убрать | M+M (UI last) |
| D14 | ABSENT | финальная reconciliation + Help + plans-sync | L (строго последний) |

P0-очерёдность по v6 §D: D01, D02, D03, D04, D06, D07, D08 (быстрые победы: D08-тумблер S, D09-`or 7` S).
