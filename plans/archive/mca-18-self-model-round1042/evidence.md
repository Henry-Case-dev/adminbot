# evidence.md — `mca-18-self-model`, Builder Block A+B (T-5075…T-5078), 06.10.2026
# ОБНОВЛЕНО: Block C+D+E+F (T-5079…T-5091) — см. разделы в конце файла.

**Fingerprint:** база HEAD `23cb2a1` (прод 2.58.61, SQLite v30); рабочий tree — изменены
`config/settings.py`, `services/database.py`, `services/mca_events.py`,
`services/mca_gates.py`; новые `services/mca_self_model.py`,
`tests/test_mca18_self_model_block_a_round1042.py`,
`tests/test_mca18_memory_subject_block_b_round1042.py`,
`tools/_mca18_reissue_f8.py`; guard-бампы `tests/test_mca10b_random_applications_block_a_round1041.py`
(frontier 73→76 / 247→250 / v30-pin ≥),
`tests/test_mca05_episodes_stories_round1027.py` (tail-mark v30→v31, конвенция волн).
`plans/current_task.md`, `services/bot_persona.py`, `services/pg_db.py` — НЕ тронуты
(проверено `git status` + `rg`). Коммит/стейдж — нет (по ограничению). Окружение:
Windows, `.venv\Scripts\python.exe` (3.12), SQLite через aiosqlite.

---

## Блок A — T-5075 SelfModelSnapshot + resolve_self_model(scope)

**Изменения:** `services/mca_self_model.py` (новый, D1 — один модуль: snapshot +
резолвер + атрибуция/запреты; БЕЗ сервиса/провайдера):
- `SelfModelSnapshot` (frozen): agent_id/bot_user_id/identity_binding, persona_id/
  persona_version (хеш СОДЕРЖИМОГО: name/biography/overrides/is_aware_ai/updated_at —
  R2d/I-2), scope_chat_id, name/aliases/biography/style_version, traits/interests/
  relations, state (mood+TTL), positions (provenance), три `SettingState`,
  self_presentation_mode (`aware`/`in_character`), capabilities, `version`
  (производный токен, прецедент `mca_retrieval_context.compute_context_version:257`).
- Три настройки (D2): `resolve_persona_enabled` (chat_params, прецедент
  `direct_chat_service.py:4857–4861`), `resolve_is_aware_ai` (PG personas, REUSE SQL
  `bot_persona._SELECT_*_SQL`), `resolve_bot_self_awareness`. Состояния
  `False` / `null-наследовать (default)` / `ошибка` — три разных `SettingState`;
  источник наследования `chat|global|default|error`; ошибка НЕ сворачивается в False.
- Идентичность: `mca_self_identity` (v31) — сид UUID в миграции; rebind — ЯВНЫЙ
  (`DatabaseService.rebind_self_identity`, admin-действие); runtime/расхождение
  привязки видно в `identity_binding` (`bound|runtime|unbound`).
- `SelfModelDisabled` (K1 OFF, reason `self_model_disabled`) /
  `SelfModelSnapshotError` (identity read fail/missing, reason
  `self_model_snapshot_error`) — ошибки не маскируются (A58/R1b-рамка).

**T-5076:** `Capabilities`/`build_capabilities()` — источник `tool_schemas.active_tools()`
(реестр+env-гейты), НЕ биография; `can_analyze_images=False` до mca-19 (честный False);
`did_analyze_images` — только runtime-доказательство; `can_remember_everything` — всегда
False («помню» = `accessible_memory`); `capability_claim_allowed` — «могу» ≠ «посмотрел»
≠ «помню всё» (I-3). `persona_version` стабилен при смене модели/токена (R2d).

**Критерии (выполнены):** пустая персона True/False → различимый
`self_presentation_mode` + живые capabilities/authorship; OFF persona (`persona_enabled
=False`) не отменяет авторство (agent_id/bot_user_id/capabilities сохраняются);
ошибки — отдельные статусы+события, не пустота.

**OFF-паритет (K1):** структурный — `mca_self_model` НЕ импортируется ни одним
live-путём (grep: только database.py-комментарий и тесты); `bot_persona.py`
байт-в-бит HEAD (вкл. `_NO_AI_DISCLOSURE_BLOCK`); K1 OFF → `resolve_self_model`
бросает ДО любых чтений v31 (тест `test_k1_off_disabled_no_reads`, счётчик чтений=0).

## Блок B — T-5077 контракт памяти / T-5078 запреты+adoption

**Изменения:**
- **Δ DDL v31** (`database.py`, одна `MigrationStep(31, "self_model")` через реестр
  mca-14, backup-guard, идемпотентно, PG DDL=0): 4 таблицы — `mca_self_identity`
  (singleton+CHECK(id), сид ON CONFLICT DO NOTHING), `mca_trait_observations`
  (raw_text/normalized/source_refs/subject_status/legacy_ref + idx (agent_id,
  observed_at DESC), idx (chat_id, observed_at DESC)), `mca_behavior_rules`
  (стадии CHECK observed→…→superseded, version/event_dedup_hash + idx (agent_id,
  status, dimension), idx (scope, status)), `mca_adoption_links` (UNIQUE
  (subject_entity_id, opinion_ref)); `graph_facts` +9 nullable-колонок (каждая под
  guard `PRAGMA table_info`; perspective/memory_kind/scope — CHECK enum; revision
  NOT NULL DEFAULT 1; status/supersedes/weight — REUSE Epic 60) + idx (chat_id,
  memory_kind, status), idx (subject_entity_id). Self-guard индекса на `status`
  для синтетических legacy-БД (прецедент v17 spec §5).
- **Атрибуция (D4, `:1533`)**: `attribute_memory` — self только по agent_id;
  «я» в цитате → автор цитаты; «бот» без доказанного референта → `ambiguous`
  (self_trait НЕ создаётся, event `trait_attribution_ambiguous`); роли
  `role_entity_ids()` (author/quoted/forward/post/depicted — не сливаются).
- **Запреты `:1535–1544`**: guard-функции `guard_fact_not_self_trait`,
  `guard_own_output_not_proof`, `guard_trait_applicability`,
  `guard_opinion_not_fact`, `guard_belief_not_value`, `guard_paradigm_period`,
  `guard_mood_reversible`, `guard_lesson_not_identity` + сводный
  `check_typed_write` → `store_typed_memory` (guard'ы ДО записи; отказ = (None,
  verdict-причина), не молчаливый). Read-side: TraitView без applicability →
  excluded с причиной; mood без/с истёкшим valid_to → неактивен (обратимо).
- **Adoption (D4)**: `mca_adoption_links` — запись требует basis_refs+opinion_ref
  (иначе ValueError); позиции snapshot собираются ТОЛЬКО из opinion-фактов с
  adoption-связью («в чате принято X» ≠ «я предпочитаю X»; повтор фразы группой —
  world_fact, позицией не становится).

**Kill-switches:** ровно 3, env-only ClassVar (`settings.py`), default ON, per-call
резолв `mca_gates` (73→76): `MCA_SELF_MODEL_ENABLED` (K1, гейтит только мои пути),
`MCA_TRAIT_RULES_ENABLED` (K2 — блоки C/D), `MCA_LEGACY_TRAITS_MIGRATION_ENABLED`
(K3 — блок E). K2 OFF: traits/state пустые, `rules_status='disabled'` (тест).
**reason_code +3 (247→250)** — только испускаемое блоками A/B подмножество санкции
+10: `self_model_disabled`, `self_model_snapshot_error`,
`trait_attribution_ambiguous`; оставшиеся 7 — блоки C–F.

---

## Фокус-проверки (точные команды + счётчики)

```
.venv\Scripts\python.exe -m pytest tests\test_mca18_self_model_block_a_round1042.py
  tests\test_mca18_memory_subject_block_b_round1042.py -q
  → 37 passed (A: 14, B: 23), exit=0

.venv\Scripts\python.exe -m pytest tests\test_mca18_self_model_block_a_round1042.py
  tests\test_mca18_memory_subject_block_b_round1042.py
  tests\test_mca05_episodes_stories_round1027.py
  tests\test_mca09_intents_block_a_round1040.py
  tests\test_mca16_experience_block_a_round1039.py
  tests\test_mca10b_random_applications_block_a_round1041.py
  tests\test_mca14_schema_additive_round1027.py tests\test_database.py
  tests\test_round1025_f8_registry.py tests\test_param_catalog.py
  tests\test_settings_persistence_round1014.py tests\test_bot_persona.py
  -q --tb=no -p no:cacheprovider → 364 passed, exit=0

.venv\Scripts\python.exe -m pytest tests\test_bot_persona.py
  tests\test_mca08_style_form.py tests\test_mca08_character_speech.py
  tests\test_mca09_intents_off_parity_round1040.py -q → 162 passed
```

Покрытие тестов по критериям:
- **v31 DDL**: fresh (frontier ≥31, 4 таблицы, 6 индексов, книга v31, сид UUID);
  идемпотентный re-init (0 дублей, agent_id стабилен); **v30→v31 simulation**
  (DROP v31-объектов + user_version=30 → re-init: backup `pre_migration_*.db` +
  **read-back** sqlite3: user_version=30, данные graph_facts целы); PG no-op
  (текст-гвард `pg_db.py` не содержит SelfModel-объектов).
- **T-5075**: состояния трёх настроек (default/chat/global/error; is_aware_ai:
  chat→global→default→pg_unavailable→exception); пустая персона True/False;
  OFF-authorship; snapshot_error not masked (+event); K1 OFF no-reads.
- **T-5076**: capabilities == `active_tools()`; no-image-claim; «посмотрел» только
  с evidence; «помню всё» False; persona_version стабилен при смене bot_user_id,
  меняется с биографией.
- **T-5077 (A59)**: self/цитата-чужая/цитата-своя/другой-бот/ambiguous/роли;
  typed roundtrip (revision=1, REUSE status/weight); CHECK-рубеж (bogus
  perspective/memory_kind/scope → отказ).
- **T-5078**: 8 запретов таблицы — по негативному тесту на каждый; write-guard
  self_trait (субъект+applicability); mood TTL; own-output-not-proof; adoption
  requires basis; UNIQUE; group-repetition ≠ position; mood read-side
  (chat>global, expired → None); K2 OFF inert.

## DDL v31 — верификация локально

- Fresh: `PRAGMA user_version ≥ 31`; 4 таблицы; 6 индексов (2+2 таблицы + 2
  graph_facts); `schema_migrations` строка v31 `self_model`; сид `mca_self_identity`
  — ровно 1 строка (uuid4).
- Повтор: второй `initialize()` — no-op (0 дублей; agent_id не меняется).
- v30→v31: simulated downgrade → re-init; backup-guard создал `pre_migration_*.db`,
  read-back: `user_version=30`, типированный факт цел; после апгрейда frontier ≥31.
- Cold-совместимость: старый код v30 v31-объекты не читает (нулевая проводка);
  legacy-v12 synthetic DB — деградация индекса без падения (тест
  `test_mca14_schema_additive_round1027.py::test_legacy_v12_backfill` зелёный).

## Каталог / F8 — ВЫПОЛНЕНИЕ ЗАБЛОКИРОВАНО ПРОТИВОРЕЧИЕМ (для @Orchestrator/@Architect)

**Санкция spec §8.2/§8.3 («Δ каталога +1 `flags.persona_enabled`, F8 510→511»)
НЕИСПОЛНИМА как сформулирована:** ключ `flags.persona_enabled` УЖЕ является
pg_key существующей записи каталога `PERSONA_ENABLED`
(`param_catalog.py:1182`, round 10.14/H3-фикс; `pg_key = {category}.{snake}` =
`flags.persona_enabled`), см. `plans/archive/settings-persistence-audit-round1014/inventory.tsv:297`.
Проверено на HEAD: `get_by_pg_key('flags.persona_enabled')` → spec `PERSONA_ENABLED`
(bool-каст override'ов работает: `'false'→False`; per_chat=True; группа
flags_memory → вкладка memory_rag). Добавление второй ParamSpec с тем же pg_id
даёт дубль pg_key (511 строк TSV / 510 уникальных ключей) и роняет инвариант
`test_round1025_f8_registry.py::test_rows_complete_no_empty` — воспроизведено.

**Сделано:** процедура F8-переиздания отрепетирована полностью
(`tools/_mca18_reissue_f8.py`, прецедент `_mca16_reissue_f8.py`): TSV/meta/screen-map
регенерировались, fixtures/guards (48 файлов) бампались 510→511 — затем ВСЁ
откачено (`git checkout --`) до HEAD-510; оставлен только скрипт с документацией
находки (включая нюанс: delta остаётся 99 — ключ в inventory 10.14, статус OK не new).
**Функционально ничего не потеряно:** runtime-ключ/каст/наследование уже работают
через существующую запись; T-5075 не зависит от Δ. Требуется решение @Architect:
либо пере-санкция «Δ каталога = 0 (ключ существует)», либо другой ключ для +1.
F8-тест на HEAD зелёный (29 passed).

## Incidental findings

1. **`related-nonblocking`**: `_build_positions` изначально был написан как
   async-генератор — `resolve_self_model` молча глотал бы TypeError через
   fail-open except. Исправлено в этом же слайсе ( coroutine → tuple), т.к. это
   корректность нового кода (не отдельная проблема).
2. **`unrelated/pre-existing`**: предупреждение «closed 7 leaked aiosqlite
   connections» исходит из старых тестов mca-05/mca-10b (не закрывают все DB);
   мои файлы — 0 утечек (проверено точечным прогоном). Не чиню — вне слайса.
3. **`unrelated/pre-existing`**: tail-mark конвенция (`test_mca05…:196`) требует
   бампа при каждом новом хвосте реестра — обновлено до v31 по конвенции волн
   (это ожидаемый расход, не дефект).

## Незакрытые риски / что дальше (для Builder-2, блоки C–F)

**[ИСПОЛНЕНО Block C–F — см. конец файла; пункт «каталог-Δ» закрыт ре-санкцией
errata (Δ=0, F8 НЕ переиздаётся).]**

- ~~Проводка frame в `build_persona_prompt_block`~~ — исполнено (T-5081).
- ~~lifecycle/анти-самоусиление/legacy-разбор~~ — исполнено (T-5079/5082/5084).
- ~~reason-коды~~ — frontier 257 достигнут (T-5084-блоки C–F добрали +7).
- ~~Env-пороги 0.1/0.2~~ — добавлены (T-5082); `MCA_MOOD_TTL_HOURS` — с блока A.
- aliases/interests/relations snapshot — честно пустые (без фабрикации);
  наполнение — REUSE mca-03 display-алиасы при будущей проводке (вне Wave-4
  slice: данных-источников в v31 нет, фабрикация запрещена).
- ~~Каталог-Δ~~ — ЗАКРЫТО: errata 06.10.2026 (ре-санкция @Architect): Δ=0.

---

---

# Блоки C+D+E+F — Builder-2 (T-5079…T-5091), 06.10.2026

**Fingerprint (продолжение того же tree):** изменены `services/mca_self_model.py`
(lifecycle+компилятор+fallback+holder), `services/bot_persona.py` (швы `:237`/
`:368` + F-3 в `get_traits` + CharacterReadContext.frame_version),
`services/database.py` (+`observation_exists_by_legacy_ref`, SELECT rules +
source_observation_ids), `services/dream_worker.py` (K2-хук наблюдений в
`_run_persona_traits_once`, аддитивно), `services/memory_maintenance.py`
(тик `legacy_traits_parse` 3600с, K3), `services/mca_process_registry.py`
(placeholder `self_model.update` v0 → реальный `self.model` v1, 8 стадий,
_GATE_RESOLVERS +3), `services/mca_events.py` (+7 кодов → 257),
`config/settings.py` (+0.1/0.2/TTL), `services/mca_gates.py` (+3 резолвера
лимитов), `services/direct_chat_service.py` (CoordinatorDecision.frame_version
аддитивно + ledger-маркировка `_mca18_ledger_source`), `web/api/routes.py`
(+4 endpoint'а), `web/index.html`+`web/app.js` (карточка «Что сейчас формирует
характер» в существующем экране «Личность»); tests: +4 новых файла
(lifecycle C+D, block E/F, contract, paired replay) + guard-бампы
(mca-10b kill-switch/reason frontier, mca-05 tail-mark — ранее; mca-17a
future-features: `self_model.update` заменён `self.model` v1).
`plans/current_task.md` не тронут; mca-09/10b/10c/12/17c/19 зоны — не тронуты
(кроме санкционированного amend плейсхолдера реестра — прецедент mca-15/16).

## Блок C — T-5079/T-5080 (lifecycle + компилятор)

- **T-5079**: `record_trait_observation` (дедуп по исходным событиям; новое
  имя dimension от LLM → NULL = неприведённое), `promote_observation`
  (авто-валидация: субъект=self доказан → источник существует → конфликт с
  ядром `CORE_CONFLICT_MARKERS` (детерминированные маркеры в owner-оверрайдах,
  engineering default) → активация), 8 `INITIAL_DIMENSIONS` +
  `DIMENSION_INSTRUCTIONS` (2-е лицо, обязательство сохранить задачу),
  `supersede_rule`/`suspend_rule`/`reactivate_rule` (терминальное НЕ
  реактивируется). `quality_regression`/`utility` → FOREIGN_DIMENSIONS:
  правило НЕ создаётся, маршрутизируется в mca-16-наблюдение (тест
  `test_quality_regression_never_a_rule`). Активация: chat-правило получает
  chat-bound applicability (запрет «всем темам», `:1539`); global без условий
  остаётся кандидатом до владельца (`:1584`).
- **T-5080**: `select_behavior(snapshot, bundle) -> BehaviorFrame`
  (детерминирован; precedence scoped_request > derived_traits — разовая
  просьба «без резкости» затеняет dimension НА ответ, черта цела; стем-матч
  RU-морфологии); `RejectedRule` с причинами; opinion ≠ factual_constraint
  (позиции — отдельный слот кадра); `render_frame_block` — стабильная статика
  + правила 2-го лица; **новая формулировка False** `SELF_MODEL_FALSE_BLOCK`
  ЗАМЕНЯЕТ `_NO_AI_DISCLOSURE_BLOCK` (D3); A58: пустая персона →
  различимый минимум (aware: тех-идентичность; in_character: образ-строка).

## Блок D — T-5082/T-5083 (анти-самоусиление + границы)

- **T-5082**: `reinforce_rule` — дедуп по `event_refs_hash` (тот же эпизод →
  no-op `trait_reinforcement_dedup`); собственные ответы под чертой НЕ
  независимы (`_rule_sources_independent`: fact → origin bot_self_reply →
  `mca_bot_outputs.source_feature` содержит `trait:{id}:v{n}`); шаг ≤0.1/цикл
  и ≤0.2/24 ч (env `MCA_TRAIT_MAX_STEP_*`, `trait_step_limit`); ослабление
  (delta<0) без капа; повторное наблюдение НЕ двигает version/target_value.
  Маркировка: `rule_tag` → `set_run_frame().applied_tag` → direct-путь пишет
  `source_feature="direct_chat|trait:12:v3;..."` (`_mca18_ledger_source`).
- **T-5083**: lesson ≠ trait (guard + NULL-dimension candidate), парадигма
  вне периода неприменима, style request ≠ trait (затенение, не удаление),
  mca-22 own-outputs — не подтверждение (кросс-тесты в C-файле).

## Блок E — T-5084/T-5085/T-5086

- **T-5084**: `run_legacy_traits_parse` (тик `memory_maintenance`, K3;
  bounded batch 200): manual → subject self доказан (действие владельца) →
  promote; deep_sleep/прочее → observation-кандидат + `legacy_trait_unverified`
  (НЕ active; rules.dimension NOT NULL по санкции §8.1 — кандидат живёт в
  observation); повтор = no-op по `legacy_ref` (fail-closed на ошибке
  lookup'а — дубли исключены); source_refs = `legacy_trait:{pg_id}`
  (реальное происхождение, фабрикация запрещена); chat→global НЕ выполняется;
  FIFO persona_traits не теряет наблюдение (raw дословно; тест ротации);
  PG down → честный `self_model_unavailable`.
- **T-5085**: `GET /api/persona/self-model` (компакт: 3 переключателя
  value+source+explanations, версии, stale/fallback, active/applied/rejected
  правила, composition base/dynamics/mood/versions, widget_id), `POST
  /api/persona/rules/{id}/pause|resume` (правка владельца = основание
  `owner_paused`/`owner_resumed`), `GET .../sources` (наблюдения/refs — R17:
  без сырых текстов). UI: карточка в СУЩЕСТВУЮЩЕМ экране «Личность»
  (index.html) + методы app.js — без нового раздела/маршрута (CA-18-8);
  три статуса различимы (applied_now ≠ оценка ≠ replay).
- **T-5086**: реестр mca-17a — `self.model` v1 (amend placeholder
  `self_model.update` v0, прецедент mca-15/16), стадии `observation_read`…
  `prompt_render` (7 instrumented; `final_check` объявлен, НЕ
  инструментирован — form-guard mca-08 K4 не трогается, честная пометка в
  note), `stages_to_events` → событие `self_model`, `_GATE_RESOLVERS` +3.
  Стадии эмитятся на реальном пути: resolve/selection (per run),
  activation (lifecycle), prompt_render (точка сборки); K1 OFF → честный
  `disabled` (payload + событие).

## Блок F — T-5087/T-5088

- **T-5087 (F-3 закрыт)**: `get_traits` fail-open → warning + событие
  `self_model/observation_read/self_model_unavailable`; ошибки frame-пути →
  событие + legacy-рендер (не маскирование); пояснение переключателей в UI
  («Рефлексия собственных ответов» — в explanations payload).
- **T-5088**: `resolve_self_model`: PG down (is_aware_ai error-state) →
  LKG со stale-маркером (TTL `MCA_SELF_MODEL_FALLBACK_TTL_SECONDS`, ttl≤0 →
  LKG запрещён) → иначе минимальная тех-идентичность; честные reason-коды
  `self_model_stale`/`self_model_unavailable`; fallback-события НИКОГДА с
  outcome=success; stale-кадр рендерится без правил/настроений (fallback
  честен); LKG не входит в `version`.

## Фокус-проверки (точные команды + счётчики)

```
.venv\Scripts\python.exe -m pytest tests\test_mca18_lifecycle_block_c_round1042.py -q
  → 24 passed (T-5079…T-5083)
.venv\Scripts\python.exe -m pytest tests\test_mca18_block_ef_round1042.py -q
  → 12 passed (T-5084…T-5088)
.venv\Scripts\python.exe -m pytest tests\test_mca18_contract_round1042.py -q
  → 7 passed (T-5089, §28.7)
.venv\Scripts\python.exe -m pytest tests\test_mca18_paired_replay_round1042.py -q
  → 6 passed (T-5090)
.venv\Scripts\python.exe -m pytest tests\test_mca18_*.py (6 файлов) -q
  → 86 passed, exit=0
.venv\Scripts\python.exe -m pytest [12-файлов смежных: mca-05/08/09/10b/14/16/17a,
  database, f8_registry, param_catalog, settings_persistence, bot_persona] -q
  → 364+133… см. интегрированный прогон ниже
```

**T-5091 (полная регрессия — исполнено, 06.10.2026):**

```
.venv\Scripts\python.exe -m pytest tests -q --tb=no -p no:cacheprovider
  → МОЙ tree:   12072 passed, 7 failed, 1 skipped (7:12)
  → чистый HEAD (git stash push -u → прогон → pop):
                11986 passed, ТЕ ЖЕ 7 failed (6:48)
  ⇒ 12072 − 11986 = 86 = мои новые mca-18 тесты; Δ новых падений = 0.
```

**Классификация 7 красных (все pre-existing, верифицировано прогоном чистого
HEAD — те же 7 в том же порядке):**
1. `test_tool_loop…test_query_chat_memory_count_reaches_model` —
   время-зависимое окно фразировки («за последний час» vs даты) — flaky.
2–4. `test_webapp_{design_tokens,f6,hotfix6}…test_app_version*` — устаревшие
   пины «2.58.57» при проде 2.58.61 (settings.py:3106) — stale с round 10.37;
   актуальный bump 2.58.62 — T-5094 (deploy), не этот slice.
5. `test_webapp_nav_disclosure_ui…test_memory_rag_and_sleep_tabs` —
   структура/маркировка вкладок — pre-existing.
6. `test_webapp_status_control…test_status_public_for_all_roles` —
   RBAC статус-эндпоинта — pre-existing.
7. `test_mca09_intents_block_e…test_registry_process_intent_initiative` —
   order-зависимый flake: зелёный standalone/группами/на чистом HEAD-батче,
   красный в обоих ПОЛНЫХ прогонах (и в моём, и на чистом HEAD) —
   межтестовое загрязнение реестра/гейтов вне mca-18.

**Исправленные в T-5091 мои guard'ы (были красными в первом прогоне):**
- `test_mca01_tx_task_supervisor…test_write_points_go_through_single_writer` —
  single-writer guard насчитал +6 моих write-точек (все через
  `write_transaction` — guard сработал как задуман); allow-list 176→182
  (mca-09/mca-10b прецедент бампа).
- `test_mca10b_block_d…test_blockE_f8_check_green_and_baselines` —
  локальный пин `ROUTES_SHA256_F11` → новый hash (routes +4, L-F11S-1).
- `test_webapp_js_unit…test_js_unit_routing_and_scope_guard` — JS-harness
  вызывает `loadPersona` с custom-this без методов → typeof-гвард на
  `loadSelfModel` (prod Vue-инстанс метод имеет всегда).

**JS:** npm-раннера нет (`package.json` scripts.test = stub); JS-проверки —
python-driven (`test_frontend_tab_mapping/test_webapp_parity_smoke` — 94
passed) + node js_unit (`test_webapp_js_unit` — зелёный в финальном прогоне).

**Holdout/replay статус (T-5090):** harness готов + 6 тестов контура
(30 сценариев, рубрика frozen, слепой оценщик, эффект≠шум, no-send); РЕАЛЬНЫЙ
прогон 30×≥3 требует LLM-бюджета (учёт mca-11) и не выполнялся (запрет
платных вызовов в slice) — `rule_verified` до прогона НЕ заявляется (R7c).

## OFF-паритет K1–K3 (блоки C–F)

- **K1 OFF**: `resolve_self_model` → `SelfModelDisabled` до любых чтений v31;
  `resolve_character_context` — frame-путь пропущен (тест: 0 событий, legacy
  ctx); `build_persona_prompt_block` — legacy-ветка байт-в-байт (включая
  `_NO_AI_DISCLOSURE_BLOCK`); `/api/persona/self-model` → `enabled: false`
  (честный disabled), rules-маршруты → 409; self.model в реестре —
  disabled/not_run (гейт-карта).
- **K2 OFF**: `record_trait_observation` → None (v31 инертна, тест);
  `promote/reinforce` → `trait_rules_disabled`; snapshot.traits пустые,
  `rules_status='disabled'`.
- **K3 OFF**: джоб legacy-разбора не регистрируется в планировщике;
  `run_legacy_traits_parse` → `disabled` (тест).
- Дрим-хук наблюдений — под K2; maintenance-тик — под K3; live-проводка
  (resolve/render/decision/ledger) — под K1.

## reason_code — итог санкции +10 (247→257, дубликатов нет)

`self_model_disabled`, `self_model_snapshot_error`,
`trait_attribution_ambiguous` (блоки A/B) + `self_model_unavailable`,
`self_model_stale`, `trait_conflict_core`, `trait_step_limit`,
`trait_reinforcement_dedup`, `legacy_trait_unverified`, `trait_rule_rejected`
(блоки C–F). Проверено: `len(REASON_CODES) == 257`, dupes=[].

## Наблюдаемость (GEN-R17)

Событие `self_model` (стадии реестра в `stage=`), R17-safe
(ID/коды/enum/числа/refs; сырые тексты НЕ логируются — sanitize единым
каналом mca-13). Per-rule причины — в `rejected_rules` кадра и payload
`/api/persona/self-model` (`excluded_reason`, `rejected_now[].reason`).
Widget-ID «Что сейчас формирует характер» — контракт mca-17c (рендер не здесь).

## Границы/ограничения реализации (для Reviewer)

1. **`CORE_CONFLICT_MARKERS`** — детерминированный engineering-default
   маркеров «ядро против dimension» (8×2–3 подстроки). Это НЕ NLP: покрытие
   неполное по замыслу; владелец правит ядром/исключениями; ложных
   срабатываний нет (точные подстроки). Альтернатива (LLM-классификатор)
   отклонена: компиляция детерминирована (`:1568`).
2. **Стем-матч scoped_request** (первые max(4,len-2) символа слова) —
   достаточен для закрытого набора 8 dimensions; не классификатор.
3. **`rules.dimension NOT NULL`** (санкция §8.1): неприведённые
   наблюдения/legacy НЕПРИВЕДЁННЫЕ кандидаты живут в
   `mca_trait_observations` (candidate-состояние), правило не создаётся —
   соответствует `:1554` («неприведённое наблюдение остаётся candidate»).
4. **Paired replay (T-5090)**: harness готов и покрыт тестами (offline,
   фейк-LLM, без платных вызовов). РЕАЛЬНЫЙ прогон 30×≥3 требует LLM-бюджета
   (учёт mca-11) и отдельного санкционирования — НЕ выполнялся (запрет
   платных вызовов в slice); rule_verified до прогона не заявляется (R7c).
5. **final_check** стадия объявлена в реестре, но не инструментирована
   (form-постпроцессор не трогается — CA-18; применение кадра фиксируется
   prompt_render + ledger-маркировкой). Честная неполнота, не имитация.
6. **Инкремент диффа mca-08**: `test_mca08_*` байт-тесты остаются зелёными —
   в их окружении frame-путь честно деградирует в legacy (нет lore-db/pg);
   в проде с K1 ON промпт меняется санкционированно (A60).

## Rework-верификация (T-5096, 06.10.2026) — H-1/H-2/H-3 по review.md

Контекст: предыдущая rework-сессия записала фиксы в дерево, но прервалась
(лимит провайдера) ДО прогонов и ДО обновления evidence. Эта сессия
верифицировала/завершила. HEAD `23cb2a1`; рабочее дерево незакоммичено
(mca-18 untracked — git-базы пре-rework у новых файлов нет, RED-доказательства
— in-place откат фикса → прогон → байт-в-байт восстановление с SHA256-сверкой).

**H-1 — FIXED (проверено кодом + тестами).** `mca_self_model.render_frame_block:
1704/1733`: контроль по вычисленному `aware` (`frame.is_aware_ai` при
отсутствии override; кадр несёт effective из snapshot `:1644–1645`; точка
сборки `bot_persona:275` вызывает без параметра — настройка проходит честно).
Контракт-тесты: `test_contract_false_block_uses_effective_awareness` +
`test_contract_empty_persona_true_false_assembly`. RED-пруф: откат финальной
проверки к параметру (`if not is_aware_ai:`) → оба FAILED; восстановление
SHA256 `49E4125D…C6B9A5D1C` — совпадение.

**H-2 — FIXED (проверено кодом + тестами).** Dream-хук `dream_worker:2501–2537`:
dimension берётся из `parse_persona_measurements` (LLM-роль маппит в закрытый
набор: `dream_prompts.PERSONA_TRAIT_DIMENSIONS` из `INITIAL_DIMENSIONS`,
промпт требует JSON «text, dimension», null → неприведённый кандидат),
`find_rule_id`/`record_trait_observation`/`promote_observation` +
`reinforce_rule` (анти-самоусиление гарды внутри). Legacy-parse
`mca_self_model:1821`: `dimension=infer_dimension(text)` (детерминированный
маппинг; нет совпадения → кандидат). Сквозные тесты:
`test_sleep_observation_to_active_rule_frame_and_tag` (сон → active-правило →
кадр → ledge-тег), `test_sleep_reinforce_only_independent_observation`,
`test_legacy_manual_mapped_dimension_becomes_active`,
`test_prompt_dimensions_match_lifecycle_closed_set`,
`test_measurements_pairs_and_legacy_tolerance`. RED-пруф: `dimension=None`
в хуке и legacy-parse (пре-rework поведение) → все три сквозных FAILED;
восстановление SHA256 обоих файлов — совпадение.

**H-3 — НЕ БЫЛ завершён, ЗАВЕРШЕНО этой сессией.** В дереве остался
`for _gen in range(1):  # PRE-FIX-SIM` — параметр `generations` был мёртв в
цикле генераций (подключён только в отчёт/evaluate). Фикс:
`range(generations)` (`tools/mca18_paired_replay.py:213`). Scaling-тест
`test_run_replay_generations_scale_and_spread`: RED пойман вживую до фикса
(`assert r3["paired_generations"] == expected_pairs_1 * 3` → `68 == 68*3`
FAILED), после фикса GREEN. Offline dry-run (PYTHONPATH, без LLM):
generations=3 → paired_generations=204 (34 хода × 2 условия × 3),
history_turns=34, llm_calls=238; `rule_verified: false` на заглушке (честно).
Раннер 30×3 остаётся live-class PENDING (запрет платных вызовов соблюдён).

**Попутно завершено (незаконченное умершей сессией):** M-1-правка
`web/api/routes.py` (фильтр sources) изменила хеш после review-бампа — оба
routes-гварда стали красными в полном прогоне (2 новых падения против базовых
7). Переутверждение по прецеденту T-5091/L-F11S-1:
`test_round1025_f8_registry.py` `ROUTES_SHA256_F11` и пин в
`test_mca10b_…block_d` → `72c22193406e6c4e201c1b75ca992808adcd728cd6dd0021
6499742ef6c4c461`. Окрестность (f8_registry + block_d + single-writer
test_mca01): 71 passed — неучтённых write-точек rework не добавил.

**Прогоны (все этой сессией, один писатель, без commit/stage):**
- Focused mca-18 (6 файлов): **93 passed** (было 86 до rework-тестов;
  +7: F-1 контракт + H-1/H-2/M-1/H-3 тесты).
- RED-проверки: H-1 → 2 failed; H-2 → 3 failed; H-3 → 1 failed (живой);
  после восстановления/фикса — все GREEN.
- Dry-run харнесс: 238 вызовов при ×3 (масштаб ровно ×3 против 102 при n=1).
- Смежный слайс (15 файлов: bot_persona, direct_chat×6, dream_worker,
  dream_persona_traits, mca-16×6): **451 passed**.
- Полный suite (санкция T-5091 повторена): прогон №1 (до бампа гвардов)
  12079 passed / 9 failed; прогон №2 (финальное дерево) **12082 passed /
  7 failed / 1 skipped (7:18)** — ровно документированные 7 pre-existing
  (registry order-flake, tool_loop flaky, 3 stale app-version пина 2.58.57,
  nav_disclosure, status_control); Δ новых падений = 0; суммы 12089 тестов
  в обоих прогонах сходятся.

**Incidental (вне bounded rework, не чинилось):** CLI-запуск
`tools/mca18_paired_replay.py --dry-run` из docstring не работает в одиночку
— нужен `PYTHONPATH=.` (`services` не на пути) и `PYTHONIOENCODING=utf-8`
(print «≠» падает на cp1251-консоли). Контур в тестах не зависит (run_replay
покрыт напрямую). related-nonblocking, Low — кандидат в backlog.

## S-1 rework (T-5093, 06.10.2026) — read-side enforcement chat-binding applicability

Blocker S-1 (Scanner): `promote_observation` ставит chat-правилу
`scope='chat'` + `applicability=["chat:<id>"]`, но read-side не сопоставлял
биндинг с чатом запуска — правило чата 111 действовало во всех чатах
(инструкция попадала в `<Persona>`). Контракт: spec §6/D8, §28.4 `:1584`
(«отношения к участнику и особенности одного чата локальны; chat→global —
явное правило и обезличивание»).

**Фикс (минимальный, один контур `mca_self_model.py`):** новый хелпер
`_scope_mismatch_reason` + проверка в цикле `select_behavior` (T-5080, сразу
после included-гарда): токены `chat:<id>` применяются только при
`snapshot.scope_chat_id == <id>`; чужой чат / глобальный запуск → правило
исключено с честной причиной `out_of_scope_chat` в `frame.rejected_rules`
(виден в UI-диагностике `rejected_now`); нечитаемый биндинг — fail-closed;
правила без chat-биндинга (global/темы) не задеты. `_compile_trait_view`
НЕ менялся (нет контекста запуска; прямые вызовы — прецедент block_b),
`list_behavior_rules` (database.py) не трогался — биндинг честно сверяется
на компиляторе кадра, через который идут все потребители (`resolve_character_context`,
web `select_behavior`). H-1 (`render_frame_block:1704/1733`), H-2
(dimension-конвейер), H-3 (`run_replay` generations) — код не тронут.

**RED→GREEN (новый контракт-тест `tests/test_mca18_s1_scope_round1042.py`,
3 теста):**
- RED до фикса: **2 failed / 1 passed** —
  `test_chat_bound_rule_not_applied_in_other_chat_or_global_run`
  (`applied_rules` чата 222 содержал CompiledRule «резкость» rule_id=11),
  `test_scanner_repro_chat111_rule_not_in_chat222_persona` (репро Scanner
  1-в-1: promote chat:111 → `resolve_self_model(db, 222)` → правило в
  applied-кадре);
- GREEN после фикса: **3 passed** (2.7s); `test_global_rule_applies_in_
  every_chat` зелёный и до, и после фикса (не-регрессия: global-правило
  «banter» работает в 111/222/global-запуске); в своём чате 111 правило
  применяется, `out_of_scope_chat` виден в rejected.

**Прогоны (один писатель, без commit/stage; PYTHONIOENCODING=utf-8):**
- Focused mca-18 (7 файлов: 6 прежних + новый): **96 passed** (93 + 3;
  Δ падений = 0).
- Смежный слайс (6 файлов: bot_persona, persona_api, persona_prompt,
  dream_worker, dream_prompts, dream_persona_traits): **112 passed**.
- Хеш кандидата `services/mca_self_model.py`: был `49E4125D…` (review
  итер.2/Scanner), стал
  `106A8F6986811582419FC6DC887CB8DBD6D2552EE0004CD905953AB1E2F1DDF2`.
- R17: дельта — только reason-коды/ID/синтетические строки; секретов и
  сырого чат-контекста нет.

**Residual (не блокер):** UI `active_rules` (snapshot.traits) по-прежнему
помечает чужое chat-правило как `included` (снапшот-терминология); фактическое
неприменение честно видно в `rejected_now` кадра. web/ вне write-scope —
для backlog-полировки. S-2 (24ч-окно) и S-3 (UNIQUE) — backlog по
диспозиции Scanner, не трогались.
