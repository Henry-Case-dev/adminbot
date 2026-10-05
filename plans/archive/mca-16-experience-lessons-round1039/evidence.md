# MCA-16 `mca-16-experience-lessons` — evidence Builder-1 (blocks A+B+C, T-4991…T-5002)

**Дата:** 05.10.2026. **База:** прод 2.58.58, HEAD `92252d1` (docs-only архив mca-10a). **APP_VERSION не менялся** (deploy/bump — T-5014 @DevOps). `plans/current_task.md` не изменялся. Коммитов нет.

## Изменённые компоненты (sha256-16 рабочего дерева)

| Файл | sha256-16 | Что |
|---|---|---|
| `services/mca_experience.py` | `36cb6cfe356af964` | новый: единый контур `ExperienceStore`/`ExperienceService`/`LessonService`/`ExperiencePolicy` + `get_service()` + `render_lessons_block`/`select_for_context` |
| `services/database.py` | `186f69cc842f5145` | v28: `_SCHEMA_VERSION_EXPERIENCE=28`, 4 DDL-таблицы + 9 индексов, `_migrate_experience_v28`, `MigrationStep(28, "experience_bank")` |
| `services/mca_gates.py` | `7620c31d1dc319d2` | KILL_SWITCHES K1–K4 (default ON) + резолверы + 9 env-only лимитов/порогов |
| `services/mca_events.py` | `5056c2aa73ebcc93` | `REASON_CODES` ровно +10 (санкция §12.4; `validation_failed` переиспользован) |
| `services/mca_retrieval_context.py` | `a8f1a7b6b50df2fb` | `LessonRef` + аддитивное `EvidenceBundle.lessons` (BUNDLE_SCHEMA_VERSION не менялся) + `tokenize_query` (публичный примитив mca-07) |
| `services/direct_chat_service.py` | `bb8e2d3278eec5b5` | отбор уроков в тот же `_build_evidence_bundle` (+`trace_id`), bounded-блок в хвост system_prompt, применения при генерации, секция в `_bundle_scoped_slice` |
| `services/provenance.py` | `8d3369f289104af8` | `ENTITY_TYPES` +`lesson` (AM-4) |
| `config/settings.py` | `d63cba271ed00f70` | K1–K4 ClassVar + env-only лимиты (ClassVar → Δ каталога = 0) |
| `tests/test_mca16_experience_block_a_round1039.py` | `d0430aaa2cd18df6` | 21 тест (T-4995) |
| `tests/test_mca16_experience_block_b_round1039.py` | `27a5509c540b931f` | 13 тестов (T-4998) |
| `tests/test_mca16_experience_block_c_round1039.py` | `823cdf0ebef8ef68` | 15 тестов (T-5002) |
| `tests/test_mca01_tx_task_supervisor_round1027.py` | `ac3a38cc3cde3e47` | census `database.py` 165→168 (+3 commit v28, конвенция L-MCA14-3) |
| `tests/test_mca05_episodes_stories_round1027.py` | `aacba89580a1a21c` | tail-mark реестра v27→v28 (конвенция волн) |

## DDL v28 — локальная верификация

- Fresh DB → `PRAGMA user_version = 28`; таблицы `mca_experience_episodes`, `mca_experience_feedback`, `mca_lessons`, `mca_lesson_applications`; **9 индексов** (`idx_mca_experience_episodes_{idem,chat_created,scope_task}`, `idx_mca_experience_feedback_{dedup,chat_created}`, `idx_mca_lessons_{status_scope,type_status}`, `idx_mca_lesson_applications_{dedup,lesson}`); книга `schema_migrations` — ровно 1 строка `(28, experience_bank)`.
- Повторный `initialize()` — no-op (0 дублей).
- Симуляция v27→v28 (drop v28-таблиц, `user_version=27`, удаление строки книги) → миграция применена заново, книга 1 строка; **backup-guard сработал** (`pre_migration_*.db` в каталоге БД). Тесты: `test_v28_fresh_schema_book_and_idempotent_reinit`, `test_v28_upgrade_from_v27_simulated`.
- PG — no-op by construction: v28-код не трогает `services/pg_db.py` (файл не изменялся), все записи — SQLite `write_transaction`.
- Аддитивность/rollback: старый код таблицы не читает; v28 инертна при K1 OFF.

## OFF-паритет

- **K1 `MCA_EXPERIENCE_LESSONS_ENABLED`** OFF: capture/feedback/propose → None, selection `disabled`, `render_lessons_block` → "", 0 записей; модуль инертен (`test_k1_off_inert`).
- **K2 `MCA_EXPERIENCE_FEEDBACK_ENABLED`** OFF: feedback-контур закрыт кроме `technical`; технические эпизоды продолжают фиксироваться (`test_k2_off_feedback_closed`).
- **K3 `MCA_EXPERIENCE_REVIEW_ENABLED`** OFF: propose/validate/activate/suspend/recheck — no-op, статусы заморожены; отбор уже `active` при K4 ON работает (`test_k3_off_statuses_frozen_selection_still_works`).
- **K4 `MCA_EXPERIENCE_CONTEXT_ENABLED`** OFF: уроки не отбираются/не включаются, применения не пишутся, bundle/срез без lessons; сбор опыта продолжается (`test_k4_off_no_lessons_but_capture_continues`, `test_build_evidence_bundle_carries_lessons` K4-OFF-ветка).
- K1–K4 в `KILL_SWITCHES` default ON + settings ClassVar default True (`test_sanctioned_registries`); env-only, Δ каталога = 0.

## Focused-команды и результаты

| Команда | Результат |
|---|---|
| `pytest tests/test_mca16_experience_block_a_round1039.py` | **21 passed** (T-4995) |
| `pytest tests/test_mca16_experience_block_b_round1039.py` | **13 passed** (T-4998) |
| `pytest tests/test_mca16_experience_block_c_round1039.py` | **15 passed** (T-5002) |
| `pytest <все 3 mca16-файла>` | **49 passed** |
| `pytest <все 33 test_mca*.py>` (соседний пакет: mca-01/03/04a/04b/05/06/07/08/10a/11/13/14/15/17a/22 + mca16) | **1074 passed** |
| `pytest tests/test_mca01_tx_task_supervisor_round1027.py` | 33 passed (после census-конвенции) |
| `pytest tests/test_mca22_truthset + mca10a_block_b + mca06` | 83 passed |
| `pytest tests/test_mca15 + mca17a + mca11_tool_result` | 199 passed |

## Покрытие блоков

- **A (T-4991…T-4995):** поля эпизода + R17 (свободный текст/секретоподобное не сохраняется), идемпотентность trace/feedback после рестарта, эпизод без trace/operation/feedback не создаётся; scope-изоляция чатов, global-anonymity (канон; цитаты/ID не проходят), урок не меняет system prompt/права (крафт отклонён), SourceRef/EvidenceLink (derived_from) для оснований; отбор scope/active→compat→relevance→utility (высокий utility без семантики не проходит), suspended не в bundle, bounded ≤5/≤600 + `ExcludedItem budget_exceeded`, lessons — отдельный тип в единственном bundle (прод-путь `_build_evidence_bundle`); полезность Beta(1,1)/ESS=2, neutral 0.5, unknown не обновляет, только применённые, журнал применения с dedup, «повтор/поздний/отменённый → без двойного обновления»; события notable-only с санкционными кодами.
- **B (T-4996…T-4998):** владелец ≠ участник, «ты врёшь» → `llm_hypothesis` (пересмотр), social → weak, LLM → hypothesis; технический исход только своей стадии (HTTP 200 ≠ истина); молчание = unknown; запоздалая связь по trace + dedup после рестарта; cancel/correct с сохранением истории; injection-текст не попадает в `signal_json`/рекомендацию/урок; feedback не активирует урок в одиночку; соц. большинство не улучшает utility; числа агрегатов/расходы/квота/счётчики не входят в utility (closed measurements, отсутствие cost/quota в сигнатуре и модуле).
- **C (T-4999…T-5002):** candidate не применяется/не активируется без проверки; включение сразу (без Human Gate); явное предпочтение → только `user_in_chat` + permission/conflict/identity; техфикс → воспроизведение + контрольный пример + инварианты; обобщение → ≥3 независимых эпизода (дубли не считаются); global — только обезличенный техурок; delta-версии + supersede + merge lineage; противоречие → активация отклонена, suspend; compat-инвалидация → stale → recheck (успех/провал→suspend); изменение источника распространяет recheck; bootstrap — только candidate historical/unverified + свежая проверка, legacy без trace не восстанавливает успех; K3 OFF — статусы заморожены.

## Reused evidence

- mca-07 bundle: `tests/test_mca07_retrieval_context_round1027.py` (в пакете 1074) — аддитивное поле не сломало bundle-контракт; `BUNDLE_SCHEMA_VERSION` не менялся.
- mca-14 runner/backup-guard: `tests/test_mca14_schema_additive_round1027.py` — реестр/книга/идемпотентность (в пакете).
- Конвенции census: `test_mca01` (165→168, L-MCA14-3), tail-mark: `test_mca05` (v27→v28).
- События/словарь: `tests/test_mca13_event_contract_round1027.py` (в пакете).

## Не выполнено / недоступно (осознанно)

- Полный suite не запускался (focused + соседний MCA-пакет; release-policy прогон — T-5012).
- PG-runtime не проверялся: v28 не содержит PG-кода (no-op by construction), `pg_db.py` не изменялся.
- Деплой/миграция на прод-БД, live-проверка — T-5014/T-5015 (не в моём скоупе).
- Каталог/F8/UI/process-registry/событийная витрина — блоки D–F (Builder-2; reason-коды и события уже заведены).
- Retention-prune (`mca_experience_episodes` 90д / feedback+applications 180д) — шаг review-job, T-5003 (Builder-2): политика-аксессоры готовы (`ExperiencePolicy.*`).

## Примечания / риск

- Spec-внутреннее расхождение имён: feedback-таймстамп `ts` (§2) vs индекс `(chat_id, created_at)` (§8) — реализовано `ts` + индекс `(chat_id, ts)` (доминирующая колонка контракта §2).
- Порог `MCA_LESSON_RELEVANCE_MIN_SCORE` стартовый `0.34` (инженерный, GEN-R27), семантика — token-покрытие запроса с FTS-подобной stem (общий префикс ≥5) на примитивах mca-07; второй retrieval-движок/индекс не создавался.
- Incidental (pre-existing, не мой): pytest-warning `closed 18 leaked aiosqlite connection(s)` в соседнем пакете — задокументирован ранее (R10.14-7, `ARCHITECTURE.md:459`), не регресс.
- Риск: интеграция в hot-path direct — покрыта focused (прод-функция `_build_evidence_bundle` + срез), но полный e2e direct/System2 — T-5010/T-5012.

---

# MCA-16 — evidence Builder-2 (blocks D+E+F, T-5003…T-5012)

**Дата:** 05.10.2026. **База:** прод 2.58.58, HEAD `92252d1` (docs-only архив mca-10a). **APP_VERSION не менялся** (deploy/bump — T-5014 @DevOps). `plans/current_task.md` не изменялся. Коммитов нет.

## Изменённые компоненты (sha256-16 рабочего дерева; Builder-2)

| Файл | sha256-16 | Что |
|---|---|---|
| `services/mca_experience_jobs.py` | `71a3d380a1c06024` | новый: `experience.review` (kind/owner/coalesce, capture-cursor, propose, validate/activate, suspend, outcome-link, utility_updated, recheck, prune, `tick_experience_review`, `temporal_holdout_report`, `recent_draw_observations`) |
| `services/mca_experience.py` | `aa9d001a2cd78b71` | enqueue при содержательной коррекции (fail-open) + фикс `current_config_version()` (`APP_VERSION` — модульная константа) |
| `services/memory_maintenance.py` | `58ba23daefdf2ea5` | тик review опыта (15 мин, hot-каденция без рестарта) в существующем планировщике |
| `services/status_service.py` | `4029bdf141aba2b5` | `experience_snapshot` (лента «Опыт», A57) + аддитивное поле `experience` в `/api/status` |
| `services/mca_process_registry.py` | `985a6f00910905ae` | `self_learning.run` v0→v1 (10 стадий, notable-события, widget-ID, recovery, gate) |
| `services/param_catalog.py` | `ad21a6a87ef6d6c6` | группа `memory_experience` + 2 параметра + select + TAB_RULES in-place |
| `config/settings.py` | `f767c6aec81d3ac0` | `EXPERIENCE_LEARNING_ENABLED`/`EXPERIENCE_REVIEW_CADENCE` (migratable, default true/daily) |
| `web/api/memory_agi.py` | `13f857631df33583` | `GET /api/memory/lessons` + `POST /api/memory/lessons/action` (admin, идемпотентно, trace только своего чата) |
| `web/index.html` | `88bf7c06dec38e2e` | лента «Опыт» (Статус) + таблица/карточка lessons (Память) |
| `web/app.js` | `1d4d8e48f247e39e` | `experienceFeed`, `loadLessons`/`lessonAction`/`saveLessonCorrection`/`openLessonTrace`, зеркало TABS `memory_experience` |
| `tools/_mca16_reissue_f8.py` | `814aaf766e0e8f3d` | F8-переиздание (TSV/meta/screen + fixtures + 51 guard-файл) |
| `tests/test_mca16_experience_block_{d,e,f}_round1039.py` | `0e3e0952151c894e`/`630de180b74181bc`/`2d971dce808cdcc5` | 16/13/13 тестов |
| `tests/js/round1039_experience_lessons_test.js` | `bc0dee46113b212c` | JS: лента/таблица/права/trace/зеркало TABS |

## Блок D (T-5003/T-5004) — review-job

- Один тип job в СУЩЕСТВУЮЩЕЙ очереди: `kind="experience.review"`, `owner="mca16"`, `coalesce_key="experience.review:global"` (singleflight; `TaskJobStore.enqueue`), durable checkpoint/counters в `task_jobs`.
- Шаги: capture-cursor (feedback + notable `tool_call` mca-11; bounded `MCA_EXPERIENCE_REVIEW_BATCH_MAX`, курсор наследуется от терминального прогона) → propose (детерминированные канонические правила P1 tool-неудачи ≥3, P2 коррекции ≥3, P3 типизированное предпочтение; дедуп по открытому уроку) → validate/activate (generalization ≥3 независимых; explicit_preference с permission/conflict fail-closed) → suspend (verified contradicts) → outcome-link (только независимый verified-исход позже применения; event_ts из `decision_json`) → utility_updated (агрегированно, 1 событие на запуск) → recheck (`recheck_stale`) → prune (`ExperiencePolicy.*`, bounded; связанное с уроками/feedback не прунится).
- **LLM-рефлексии на сообщение нет**: модуль не импортирует LLM-клиент и не делает внешних вызовов (fixture-скан). Deep sleep не смешивает lessons с парадигмами (отдельный kind/таблицы; `dream_worker`/`graph_facts` не читаются). Случайность — только журнал `mca_random_draws` как read-only наблюдение; второго RandomSource/процента нет.
- Триггеры: тик 15 мин в `MemoryMaintenanceService` (каденция/learning — `hot.get` на каждом тике → без рестарта; due-проверка по `last_completed_review_at`) + немедленный enqueue при owner/participant-коррекции.
- Тесты: `pytest tests/test_mca16_experience_block_d_round1039.py` → **16 passed** (job/singleflight/coalesce, bounded-курсор, capture feedback/tool, propose/validate/activate, предпочтение→user_in_chat, no-LLM, сон, случайность-границы, outcome-link позже+verified, utility один раз, prune-защита, дедуп/рестарт, suspend, recheck).

## Блок E (T-5005…T-5009) — настройки, витрины, наблюдаемость

- **Каталог/F8 (санкция §12.2):** REGISTRY **502→504**, GROUPS **107→108** (`memory_experience`, вкладка `memory_rag`), `_TAB_BY_GROUP` **105→106**, TAB_RULES **21 in-place**, delta **91→93**, Settings **439→441**, categorized **477→479**; secret — без изменений; `python tools/gen_param_registry_round1025.py --check` → **CHECK OK: реестр 504**; `ROUTES_SHA256_F11` = `efcbc457dae345d03bf304fdc86c8f5074937185ff1bc3b7cd635b568dea90f2` — **совпал** (routes.py не менялся); F8-скрипт обновил TSV/meta/screen-map/widget-map(+2 врезки)/fixtures и 51 guard-файл.
- Настройки: `memory.experience_learning_enabled` (bool, true) + `memory.experience_review_cadence` (select hourly/daily/weekly, daily); применение через hot; выполняющиеся решения фиксируют `config_version` (эпизоды) / policy/proposal/validator (уроки) / compat.
- «Статус»: компактная лента «Опыт» (аддитивное `experience`), реальные записи («исправлен способ действия»/«учтено предпочтение»/«урок применён»/«урок приостановлен»), честные disabled/not_run, unknown → без выдуманного улучшения (A57), чужой чат не раскрывается.
- «Память»: таблица lessons (scope/тип/статус/условия/основания/версии/применения/исходы) + карточка (пример/чему научились/где применяется/ограничения) + права suspend/activate/correct (новая версия; пустая правка → no-op) + trace разрешённого чата (иначе сервер не отдаёт). Suspended виден и не применяется.
- Наблюдаемость: `self_learning.run` v1 (10 стадий; instrumentation review/propose/validate/activate/suspend; stages_to_events на санкционные события; `state_source` v28+task_jobs; `recovery_ops`; `enabled_gate`; widget-ID «Опыт и уроки» — контракт mca-17c); OFF → `disabled/not_run`; A49-цепочка (эпизод↔trace↔урок↔применение↔job) не рвётся.
- Тесты: `pytest tests/test_mca16_experience_block_e_round1039.py` → **13 passed**; JS `node tests/js/round1039_experience_lessons_test.js` → **MCA16-EXP-OK**.

## Блок F (T-5010…T-5012) — holdout, границы, сводка

- **T-5010 (holdout):** `pytest tests/test_mca16_experience_block_f_round1039.py` → **13 passed**. Методика: урок извлекается review-прогоном только из эпизодов фазы 1 (прошлое); эпизоды фазы 2 — позже и не источники (проверка evidence links); OFF/ON на одной версии/сопоставимом запросе (OFF=K4: урок не отбирается; ON: отбор); отчёт: `validation_failures` (повтор ошибок), `block_tokens` (доп. стоимость ≤600), `improvement_measured=False`, `correctness/appropriateness=None` — replay проверяет инварианты, но не доказывает реакцию человека; число уроков не подменяет эффект (GEN-R27). Временная ось — `decision_json.event_ts` (время события), не capture-время.
- **T-5011 (чек-лист §25.7):** unknown ≠ success/failure; preference → user_in_chat (чужой участник/чат не видят); global без данных чата (ID/цифры → отказ); injection в feedback не активируется (канон); social/числа/расходы/квота не reward; regression на новом контексте (semantic gate); tool/model update → recheck (не применяется); дедуп/рестарт; suspended не в контексте; долгий playbook bounded (≤5/≤600, `budget_exceeded`); изменение источника → recheck.
- **T-5012 (интегрированный пакет):**
  - `pytest <все 36 test_mca*.py>` → **1117 passed** (baseline 1074 = 30 соседних + mca16 A–C 49; +42 новых D/E/F).
  - Sweep guard-файлов F8: `pytest <54 изменённых tests/test_*.py>` → **1960 passed**.
  - JS: `node tests/js/*.js` (все) → **59/59 OK**.
  - OFF-паритет (ad-hoc, 17 проверок): K1 OFF — capture/feedback/select/render/enqueue/tick/status/api = инертны, 0 записей; K2 OFF — owner закрыт, technical открыт; K3 OFF — job/статусы заморожены, отбор active работает; K4 OFF — уроки не отбираются/не применяются; `ALL_TRUE`.
  - R17-скан: belt-and-suspenders regex (секрет-паттерны) по 14 новым/изменённым артефактам → **0 утечек**; `gen --check` R17-чисто; витрины/API — только канон/ID/коды (тест `test_r17_windows_are_canonical_only`).

## Красные/incidental (классификация)

- **Fixed (pre-existing, test-only stale guards):** 6 release-pin тестов ждали `2.58.57` при APP_VERSION `2.58.58` (пропущены sweep'ом mca-10a) → обновлены до `2.58.58` (T-5014 при бампе — снова sweep до `2.58.59`); `react_moai` census 2→3 (mca-15 добавил silent-path numeric guard); memory-группы stale-guard (mca-10a); `EMBEDDING_QUOTA_GROUP_LABELS` stale-guard (ASAP 4.4). Не мой root cause; фиксы минимальны и перечислены.
- **Fixed (block A defect, в моём root cause):** `current_config_version()` возвращал `unknown` (`APP_VERSION` — модульная константа, не поле Settings) — исправлено; T-5005 требует config_version у выполняющихся решений.
- Red'ов в focused-пакете не осталось (1117 + 1960 + 59 + 17 зелёные).

## Не выполнено / недоступно (осознанно)

- Полный suite не запускался (focused + MCA-пакет + sweep затронутых guard-файлов); deploy 2.58.59/миграция прод — T-5014; live-часть — T-5015 (PENDING OWNER).
- LLM-гипотеза внутри пакета (допустима ≤1 вызов/запуск) — **не используется**: предложения детерминированные, платных вызовов нет; вывод LLM никогда не активация (A45).
- Исторический bootstrap: остаётся candidates-only через сервис (T-5001, блок C); review-job не делает mass-archive проход и не выдумывает эпизоды (2 млн сообщений без trace ≠ успех).
- PG-runtime: v28/новые пути PG-кода не содержат (no-op by construction).

