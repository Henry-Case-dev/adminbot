# mca-06-sleep-paradigms — Evidence (блок B+C, round 10.33)

> Feature: `mca-06-sleep-paradigms` (Wave 2). Контракты: `spec.md` §3–§4,
> `adr-1028-9-mca06-sleep-paradigms.md` D1–D4/D7, `threat-failure-analysis.md`
> THR-1/2/12/14. Задачи: T-4703…T-4712. **Без коммитов/деплоя.**

## Fingerprint

- HEAD: `4a6603bcee569bd8080a852ad65b8ea5400ef582` (base 2.58.48)
- Scope sha256 (8 изменённых/новых исходников, финальный):
  `7a9bcbed584064d795717bc129e61277d541182b1103abddf523e1ea0c4b6ec0`
- Environment: `win32-py312-venv` (+ `chromium` для UI-прогона)

## Изменённые файлы/компоненты

| Файл | Что |
|---|---|
| `config/settings.py` | 7 env-only `MCA_DREAM_*` kill-switch (default ON) + env-only константы профиля (pre-limit factor, max packets, enrich rounds/batch, backoff base/cap) |
| `services/mca_gates.py` | `DreamGateState` + `resolve_dream_gate` (8 причин, фиксированный порядок §3.2, источники chat/global/default, конкретный `detail`); 7 accessor'ов; REASON_CODES-список |
| `services/mca_events.py` | аддитивное расширение `REASON_CODES`: 8 gate-причин + `counters_error` + historical/enrichment коды (словарь один) |
| `services/mca_dream_history.py` (new) | исторический профиль: возраст от `message_timestamp`, фильтр ДО top_k, дедуп, FTS-фолбэк без vec-предусловия, тематические пакеты (bound), семантический ранкинг (тема/участники/freshness), resumable enrichment, bounded source window |
| `services/summary_memory.py` | аддитивно `message_timestamp`/`created_at` в `with_meta=True` (KNN+FTS) — retrieval по времени события (D4) |
| `services/dream_worker.py` | врезка resolver'а в `_run_deep_once`; `rag_off`/`schedule_outside_window`/`cooldown`/`resource_limit` точные причины; исторический профиль с OFF-паритетом; traits до paradigm-блокеров |
| `web/api/memory_agi.py` | `deep_sleep_status`: master/deep разъединены, `counters_error`, поля карточки (`gate/global_value/chat_override/effective/gate_source/detail`) |
| `web/app.js` | UI-карточка: метки новых причин + вывод конкретного `detail` в `.ribbon-empty__reason` |
| `tests/test_mca06_sleep_bc_round1033.py` (new) | 35 targeted-тестов B+C |
| `tools/ui_mca06_sleep_card.py` (new) | Playwright-проверка 3 fixture-конфигураций (T-4706) |
| `tools/mca06_timestamp_audit.py` (new) + `plans/reports/mca06_t4712_timestamp_audit.md` | READ-ONLY обследование timestamps (T-4712) |

## Kill-switches (7, env-only, default ON; OFF = бит-в-бит 2.58.48)

`MCA_DREAM_GATE_RESOLVER_ENABLED`, `MCA_DREAM_HISTORICAL_PROFILE_ENABLED`,
`MCA_DREAM_EVIDENCE_TYPING_ENABLED`, `MCA_DREAM_QUOTAS_SPLIT_ENABLED`,
`MCA_DREAM_RUN_REPORTS_ENABLED`, `MCA_DREAM_REVISION_QUEUE_ENABLED`,
`MCA_DREAM_RANDOM_EXPLORE_ENABLED` — все объявлены в `settings.py` и в
`mca_gates.KILL_SWITCHES`. **Блок B+C потребляет 2** (GATE_RESOLVER,
HISTORICAL_PROFILE); остальные 5 — декларации для блоков D–H (их слои вне
scope этой волны). Δ каталога = 0.

## Команды и результат

| Команда | Результат | Evidence ID |
|---|---|---|
| `py_compile` 7 модулей | PASS | `sha256:825bdbe3…` |
| `pytest tests/test_mca06_sleep_bc_round1033.py tests/test_deep_sleep.py` | **82 passed** | `sha256:ba604d6b…` |
| `pytest` sleep/dream/persona/mca13/mca07/mca05/mca14/gates/mca03 (14 файлов) | **325 passed** | `sha256:82f884eb…` |
| `python tools/ui_mca06_sleep_card.py` (Playwright) | PASS (3 fixture, 0 console errors) | `sha256:0da9a8d8…`* |
| `python tools/mca06_timestamp_audit.py <history.db>` | PASS (READ-ONLY) | `sha256:e4f8e77a…`* |

Полный pytest не гонялся (по waves). Реюз: ранее записанных PASS по этому
fingerprint не было. (*) UI-прогон и аудит БД не зависят от
cooldown/resource-fail-safe правки в resolver'е; записаны под предыдущим
fingerprint `af3e1a97…` — переиспользуемы (тот же UI/DB-вход).

### Playwright (T-4706) — фактические строки

- off → `…глубокий сон выключен (flags.deep_sleep_enabled) [flags.deep_sleep_enabled=False (source=global)].`
- master-off → `…мастер-рубильник памяти выключен… [memory.dream_enabled=False (source=global)].`
- resource-limit → `…суточный лимит… [global daily deep attempts: used=1, limit=1].`

### T-4712 — факт

`graph_facts`: total **10447**, valid `message_timestamp` **10419 (99.73%)**,
missing **28**, восстановлено bounded-поиском **0** (по `chat_id`+`fact` в
`smart_archive_facts`). Отчёт: `plans/reports/mca06_t4712_timestamp_audit.md`.

## Недоступные/отложенные проверки

- **T-4710 worker-триггер enrichment по пустому старому периоду** и носитель
  стадий/бюджета в отчёте §7.2 — блок G (T-4727). Здесь реализован и
  протестирован bounded/resumable primitive (`enrich_history`).
- **T-4704 полный scheduler-контур**: тик по-прежнему выбирает кандидатов по
  trigger/hour (это и есть schedule-фильтр); решение о прогоне вынесено в
  единый `_run_deep_once` (общий funnel для scheduler/manual/worker).
- Полный pytest / прод-прогон / deploy — вне B+C (waves).

## Остаточный риск

- `_resource_gate` опирается на глобальный `count_deep_attempts` (per-chat
  квоты — блок F/T-4723); до F `resource_limit` детализирован как «global».
- Исторический профиль активируется только при наличии
  `memory.retrieve_fact_candidates` (реальный MemoryManager); тест-даблы без
  канала остаются на OFF-пути — осознанная fail-open граница.

---

# mca-06-sleep-paradigms — Evidence (блок D+E, round 10.34)

> Контракты: `spec.md` §5–§8.6, `adr-1028-9-mca06-sleep-paradigms.md`
> D7/D8/D10/AM-5, `threat-failure-analysis.md` THR-3/THR-4.
> Задачи: T-4713…T-4722. **Без коммитов/деплоя.**

## Fingerprint

- HEAD: `4a6603bcee569bd8080a852ad65b8ea5400ef582` (base 2.58.48; B+C в дереве)
- Scope sha256 (6 изменённых/новых исходников D+E):
  `c0da8e403c33f101d99091b9279a9b79b6ec4cf29d5e156e30ec440b01a168ef`
- Environment: `win32-py312-venv`

## Изменённые файлы/компоненты

| Файл | Что |
|---|---|
| `services/mca_dream_evidence.py` (new) | ядро D+E: `primary_event_key`/`independent_events`/`excluded_bot_self`; мост-валидатор §5.3 (5 проверок); 10-статусная матрица `DREAM_STATUSES`/`LEGACY_STATUS_MAP`; `anchor_source_ref`/`record_anchor_items_provenance`/`validate_links`; `link_supersedes`/`link_contradicts`/`find_supersede_candidate`; `RevisionQueue`; `build_applicability`/`merge_applicability`; `expand_chain` |
| `services/dream_worker.py` | врезка в `_run_deep_once` (independence-гейт `min_anchors=2` на независимых событиях → `insufficient_evidence`; мост-фильтр до записи; `_paradigm_rows`/supersede-поиск), `_write_paradigm` (anchor provenance + `supersedes` + AM-5/`independent_events` в `belief_meta`), `_canon_status` (10-статусный канон при ON), `_run_deep_all` принимает `written` |
| `services/provenance.py` | read-only `get_source_ref` (SourceRef по id для цепочки) |
| `services/mca_gates.py` | `dream_revision_queue_cap()` |
| `config/settings.py` | env-only `MCA_DREAM_REVISION_QUEUE_CAP` (default 20; вне каталога) |
| `web/api/memory_agi.py` | read-only `GET /api/memory/dream/chain` (расширение существующего роутера) + `_DEEP_REASON_MAP` аддитивно (`written`, `insufficient_evidence`) |
| `tests/test_mca06_sleep_de_round1034.py` (new) | 39 targeted-тестов D+E |
| `tests/test_deep_sleep.py`, `tests/test_dead_extractor_paradigms_round1024.py` | изоляция слоя D: `_worker`-хелпер патчит `dream_evidence_typing_enabled=False` (паритет baseline; ON-контракты — в новом файле) |

## Kill-switches

- `MCA_DREAM_EVIDENCE_TYPING_ENABLED` — слои D+E (T-4713…T-4722, кроме T-4720);
  OFF → прежние `source_ids`-only, порог по числу якорей, статусы без канона.
- `MCA_DREAM_REVISION_QUEUE_ENABLED` — очередь пересмотра (T-4720); OFF →
  пересмотр не запускается. Cap — env-only `MCA_DREAM_REVISION_QUEUE_CAP=20`.
- Δ каталога = 0; DDL не добавлялся (`belief_meta` JSON + v17-таблицы REUSE).

## Команды и результат

| Команда | Результат | Evidence ID |
|---|---|---|
| `py_compile` 6 исходников + 3 теста | PASS | `sha256:c0da8e40…` |
| `pytest tests/test_mca06_sleep_de_round1034.py` | **39 passed** | `sha256:c0da8e40…` |
| `pytest` (D+E + B+C + deep_sleep + dream_worker + dream_prompts + persona_traits + mca04a_provenance + memory_health ×2) | **225 passed** | `sha256:c0da8e40…` |
| `GET /api/memory/dream/chain` регистрация роутера | PASS (в списке `memory_router.routes`) | — |

Целевые якоря: independence `(chat_id,tg_message_id)` — `test_two_retellings_one_message_is_one`/
`test_bot_self_excluded_from_independence`; мост — `test_random_old_fact_no_subject`/
`test_contradiction_narrows_not_rejects`; порог — `test_insufficient_evidence_two_retellings`;
статусы — `TestStatusMatrix`; цепочка — `test_chain_resolves_to_message_and_delta`;
версии — `test_repeat_run_idempotent_no_new_records`; очередь — `TestRevisionQueue`;
AM-5 — `test_narrowed_applicability_in_belief_meta`.

## Недоступные/отложенные проверки

- **T-4718 Browser-Verification / карточка delta UI**: проверено раскрытие
  цепочки на **реальном API/БД** (`expand_chain`: парадигма → message+graph_fact
  → `(chat_id, tg_message_id)`; delta old→new). Playwright-прогон карточки delta
  и рендер `unchanged` в UI — интеграционный слой G (T-4727/T-4731); здесь
  API/данные готовы.
- **T-4713 counter в отчёте прогона §7.2** — носитель `report_json` создаётся
  блоком G (T-4727); здесь счётчик в `belief_meta.independent_events` и
  `_trace_deep`-extra.

## Остаточный риск / предсуществующее

- ~~5 падений `tests/test_dead_extractor_paradigms_round1024.py::TestDeepSleepStatusApi`~~
  — **RESOLVED** точечным регресс-фиксом B+C (см. блок «Регресс-фикс» ниже).
- UI-мэппинг `unchanged→empty` (`_DEEP_REASON_MAP`) не менялся (паритет OFF);
  канонический показ статусов в UI — T-4715/G.

---

# mca-06-sleep-paradigms — Evidence (регресс-фикс B+C / T-4705, round 10.33)

> Восстановление обратной совместимости `deep_sleep_status` после блока B+C.
> Контракт: `spec.md` §3.4 (master/deep split), прежний (frozen) контракт
> round1024 `TestDeepSleepStatusApi`. **Без коммитов/деплоя.**

## Fingerprint

- HEAD: `4a6603bcee569bd8080a852ad65b8ea5400ef582` (base 2.58.48; B+C/D+E в дереве)
- Изменён 1 исходник: `web/api/memory_agi.py` (`deep_sleep_status`)
- Environment: `win32-py312-venv`

## Причина регрессии

`deep_sleep_status` безусловно вызывал `mca_gates.resolve_dream_gate(...)`.
При отсутствии DreamWorker (`lore_runtime.get_dream_worker() is None`) или при
`worker.memory is None` (ср. `bot.py:669`) resolver первым делом отдаёт
`memory_service_missing` и перекрывал прежнюю причину → 5 падений
`test_status_reason_master_off` / `_from_last_skip` /
`_unchanged_maps_to_empty_not_duplicate` / `_duplicate_reason_kept` /
`_foreign_chat_log_not_used`. Причина не зависит от
`MCA_DREAM_EVIDENCE_TYPING_ENABLED`.

## Фикс

`web/api/memory_agi.py::deep_sleep_status`: вычисляется
`service_available = worker is not None and getattr(worker, "memory", None) is not None`.
Resolver вызывается (и аддитивные поля `counters_error`/`gate`/… добавляются)
**только при `resolver_on and service_available`**. Иначе — прежняя ветка
2.58.48: `master_off` при выключенных `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED`,
иначе код из `memory_dream_log` (`_last_deep_reason`) или `empty`. Новая
семантика master/deep split (`master_sleep_off`/`deep_sleep_off`/8 кодов)
сохранена, когда memory service реально доступен.

## Команды и результат

| Команда | Результат |
|---|---|
| `.venv\Scripts\python.exe -m pytest tests/test_dead_extractor_paradigms_round1024.py::TestDeepSleepStatusApi` (до фикса) | **5 failed / 2 passed** (`memory_service_missing`) |
| то же (после фикса) | **7 passed** |
| `pytest` (round1024 + deep_sleep + dream_worker + dream_persona_traits + dream_prompts + webapp_round1017_sleep + webapp_round1013_f5_ui + webapp_round1015_ui + webapp_agi_ui + webapp_gates_api + webapp_f5_round1025 + webapp_f7_round1025 + mca06_bc1033 + mca06_de1034) | **333 passed** |
| `pytest tests/test_mca06_sleep_bc_round1033.py tests/test_mca06_sleep_de_round1034.py` | **81 passed** (в т.ч. `test_master_deep_split`, `test_each_gate_distinct_reason`, `test_counters_error_not_zeros`, `test_resolver_off_parity`) |
| `python -m py_compile web/api/memory_agi.py` | **OK** |

Новых тестов не добавлено: frozen-контракт round1024 + bc1033/de1034 уже
покрывают обе ветки (service absent → legacy; service present → resolver).

## Недоступные/отложенные проверки

- Полный pytest / прод-прогон / deploy — вне scope точечного фикса.

## Остаточный риск

- Нет: обе эквивалентные ветки (memory service доступен/недоступен) имеют
  прямой тест; новых границ правка не вводит.


---

# mca-06-sleep-paradigms — Evidence (блоки F+G, round 10.35)

> Контракты: `spec.md` §6–§8.5, `adr-1028-9-mca06-sleep-paradigms.md`
> D5/D9/D11, `threat-failure-analysis.md` THR-5/6/10/11/12/13.
> Задачи: T-4723…T-4728. **Без коммитов/деплоя.**

## Fingerprint

- HEAD: `4a6603bcee569bd8080a852ad65b8ea5400ef582` (base 2.58.48; B+C+D+E в дереве)
- Scope sha256 (7 исходников F+G, финальный):
  `35511884659d517e04891e09967ceb27d8530d0d252c15227a95d77859ce08f9`
- Environment: `win32-py312-venv`

## Изменённые файлы/компоненты

| Файл | Что |
|---|---|
| `config/settings.py` | env-only `MCA_DREAM_PER_CHAT_ATTEMPTS_LIMIT` (1), `MCA_DREAM_GLOBAL_ATTEMPTS_LIMIT` (30); Δ каталога = 0 |
| `services/database.py` | `count_deep_attempts(since_ts, *, chat_id)`; `deep_error_state(chat_id)`; `latest_dream_data_ts(chat_id)`; DDL **v25** (2 nullable-колонки `chat_id`/`report_json` + `idx_mca_pipeline_runs_chat`) через реестр `mca-14` |
| `services/mca_gates.py` | `_resource_gate`: per-chat × global (OFF → прежний глобальный путь); `_cooldown_gate`: bounded backoff ≠ cooldown; accessor'ы лимитов |
| `services/mca_trace.py` | `start_run(chat_id=…)` + `_insert_run` (v25-колонка); `set_run_report` |
| `services/mca_process_registry.py` | `sleep.deep` code-declared (event_names `DREAM_DEEP_RUN`, instrumentation) + pipeline `sleep.deep` v1 |
| `services/dream_worker.py` | per-chat singleflight + manual-recheck (T-4725); durable run-строка + отчёт §7.2 (T-4726/27); запись/счётчик/статус (T-4728); resolver только при доступном memory service (регресс-паритет T-4705) |
| `services/mca_events.py` | reason-коды `backoff`, `manual_recheck` (словарь один) |
| `tests/test_mca06_sleep_fg_round1035.py` (new) | 24 targeted-теста F+G |
| `tests/test_mca06_sleep_bc_round1033.py` | `_FakeGateDb.count_deep_attempts(*, chat_id)` (fake-подпись) |
| `tests/test_sleep_manual_cascade_round1018.py` | изоляция слоя D+E (2 теста: evidence typing OFF) |

## Kill-switches

- `MCA_DREAM_QUOTAS_SPLIT_ENABLED` — per-chat/global квоты + cooldown/backoff
  (T-4723/24/25); OFF → прежний глобальный `count_deep_attempts` (limit 1) +
  общий cooldown, manual-recheck/singleflight отключены.
- `MCA_DREAM_RUN_REPORTS_ENABLED` — run-строки + отчёты (T-4726/27); OFF →
  только прежний `_trace_deep`/лог, реестр честный `not_run`.
- Δ каталога = 0.

## DDL-факт v25

`PRAGMA user_version = 25`; `mca_pipeline_runs` + `chat_id INTEGER` +
`report_json TEXT`; индекс `idx_mca_pipeline_runs_chat
(pipeline_type, chat_id, started_at)`; повторный прогон `_migrate_dream_runs_v25`
— no-op; PG no-op. Проверено: fresh in-memory `user_version 25 | chat_id True
| report_json True | idx True`.

## Команды и результат

| Команда | Результат |
|---|---|
| `py_compile` 7 исходников + 3 теста | PASS |
| `pytest tests/test_mca06_sleep_fg_round1035.py` | **24 passed** |
| `pytest` (F+G + bc1033 + de1034 + deep_sleep + dead_extractor + sleep_manual + mca17a + mca14 + external_log) | **312 passed** |
| `pytest` (dream_worker + dream_prompts + persona_traits + mca04a + webapp sleep/agi/f5/f7 + memory_health) | **223 passed** |
| `pytest` (anticliche + summary_logging_runid + summary_asap2_observability + webapp_gates_api) | **130 passed** |

Целевые якоря F+G: per-chat/global — `test_single_chat_fails_only_its_per_chat_quota`/
`test_global_cap_still_works`; backoff — `TestBackoff`; singleflight/recheck —
`TestManualSingleflight`; реестр — `TestRegistry`; отчёт/DDL — `TestRunReport`;
согласованность — `TestWriteConsistency` (`test_write_failure_after_count_is_error`).

## Регресс-паритет (точечно)

- `_run_deep_once`: resolver применяется только при `self.memory is not None`
  (как API-карточка T-4705) — восстановлен `test_external_log_round1024::
  test_deep_disabled_reason` (`reason=disabled`, не `no_memory`).
- 2 теста `test_sleep_manual_cascade_round1018` изолированы evidence typing OFF
  (проверяют traits/каскад, а не мост-валидатор D+E) — оба зелёные.

## Недоступные/отложенные проверки

- Полный pytest / прод-прогон / deploy — вне F+G (waves). Реальный Playwright-
  прогон отчёта/статусов — блок I (T-4731+).

## Остаточный риск

- Backoff «сброс при изменении настроек» реализован как пересчёт окна из
  текущих env-настроек per-call (изменение base/cap немедленно меняет окно);
  отдельного durable-снимка настроек нет (Δ DDL = 0).
- `MCA_DREAM_DAILY_ATTEMPTS_LIMIT` (legacy, OFF-путь) остаётся undeclared в
  `settings.py` (эффективно default 1) — предсуществующее, вне scope F+G.


---

# mca-06-sleep-paradigms — Evidence (блок H, round 10.36)

> Контракты: `spec.md` §8.6/§8.7, `adr-1028-9-mca06-sleep-paradigms.md`
> AM-2/AM-3, `threat-failure-analysis.md` THR-8/THR-9.
> Задачи: T-4729, T-4730. **Без коммитов/деплоя.**

## Fingerprint

- HEAD: `4a6603bcee569bd8080a852ad65b8ea5400ef582` (base 2.58.48; B+C+D+E+F+G в дереве)
- Scope sha256 (5 исходников/тестов H, финальный):
  `0ca00f5b75b7cab7326568158009f940e3f674ba479ce33155fe4017f4b3af04`
- Environment: `win32-py312-venv`

## Изменённые файлы/компоненты

| Файл | Что |
|---|---|
| `services/mca_dream_random.py` (new) | T-4730: `DreamRandomSource` (Protocol) + `DeterministicUniformRandomSource` (`pick(candidates, *, chat_id, purpose, k) -> (items, selection_meta)`; seed = `(pipeline_run_id, chat_id)`; `default_source()`); `PURPOSE_LESS_STUDIED`; `is_dream_random_source` |
| `services/mca_dream_history.py` | `select_historical_candidates(..., random_source=None)`: при источнике материал выбирает ТОЛЬКО `pick` (+`selection_meta`), иначе прежний ранжированный топ-k; `HistoricalSelection.selection_meta` |
| `services/dream_worker.py` | `_run_deep_once_core`: `MCA_DREAM_RANDOM_EXPLORE_ENABLED` ON → `default_source(pipeline_run_id)` и проброс в профиль; OFF → `None` (паритет). `_deep_report_json`: `anchors.selection` (R17-safe: seed/пул/индексы) |
| `services/mca_dream_evidence.py` | T-4729/AM-3: контракт отрицательной границы `CHARACTER_CORE_WRITE_API` / `SLEEP_DERIVED_WRITE_API` / `character_core_boundary()` / `character_core_write_blocked()` (ядро — зона mca-18, не эскизируется) |
| `tests/test_mca06_sleep_h_round1036.py` (new) | 11 targeted-тестов H |

## Kill-switches

- `MCA_DREAM_RANDOM_EXPLORE_ENABLED` (env-only, default ON) — T-4730. OFF →
  `random_source=None`, обычный ранжированный пайплайн (бит-в-бит 2.58.48);
  `selection` в отчёте не появляется.
- T-4729 — слой evidence (`MCA_DREAM_EVIDENCE_TYPING_ENABLED`), граница —
  структурная (отсутствие write-пути), не runtime-флаг. Δ каталога = 0; DDL не
  добавлялся.

## Команды и результат

| Команда | Результат | Evidence ID |
|---|---|---|
| `py_compile` 4 исходника + 1 тест | PASS | `sha256:0ca00f5b…` |
| `pytest tests/test_mca06_sleep_h_round1036.py` | **11 passed** | `sha256:0ca00f5b…` |
| `pytest` (bc1033 + de1034 + fg1035 + h1036) | **109 passed** | `sha256:0ca00f5b…` |
| `pytest` (deep_sleep + dream_persona_traits + dead_extractor_round1024 + sleep_manual_round1018 + external_log_round1024) | **141 passed** | `sha256:0ca00f5b…` |

Целевые якоря H:
- T-4729: `TestCharacterCoreBoundary` — `test_boundary_contract_declares_mca18_zone`,
  `test_dream_worker_has_no_core_write_path` (нет ни метода, ни упоминания
  `CHARACTER_CORE_WRITE_API` в `dream_worker.py`),
  `test_both_traits_branches_write_derived_not_core` (fix ON и OFF: spy
  `save_persona` не вызван, `append_traits` — вызван).
- T-4730: `test_deterministic_uniform_same_seed_same_selection`,
  `test_different_run_id_can_change_selection`, `test_selection_meta_is_r17_safe`,
  `test_select_uses_source_only_when_provided`,
  `test_explore_on_passes_source_and_records_selection`,
  `test_explore_off_no_source_ranked_parity`,
  `test_verdict_from_evidence_not_from_random_material` (разный материал +
  один вердикт валидатора → один статус; недостаток доказательств →
  `insufficient_evidence`, не `written`).

## Недоступные/отложенные проверки

- Полный pytest / прод-прогон / deploy — вне H (waves).
- Стык с mca-10a (Wave 3): контракт `DreamRandomSource` зафиксирован
  (`pick` + `selection_meta` + «случайность не влияет на вердикт»); core-источник
  mca-10a реализует интерфейс без переписывания пайплайна — проверка появится
  при активации mca-10a.
- Random exploration активен только поверх исторического профиля
  (`MCA_DREAM_HISTORICAL_PROFILE_ENABLED`); при OFF профиля — обычный
  direct-RAG-пайплайн (осознанная зависимость материала).

## Остаточный риск

- `selection_meta` пишется в отчёт §7.2 только при `MCA_DREAM_RUN_REPORTS_ENABLED`
  ON; при OFF — остаётся трасса `[pipeline] step=explore reason=random_explore`
  (R17-safe), durable-записи нет (согласовано с kill-switch отчётов).
- Граница ядра mca-18 держится структурой кода (объекта ядра здесь нет); при
  будущем SelfModel-апи mca-18 контракт `CHARACTER_CORE_WRITE_API` переиспользуется
  аудитом/тестом.


---

# mca-06-sleep-paradigms — Evidence (блок I, round 10.37)

> Контракты: `spec.md` §9.1/:381 п.8, §10 (A14/A93/A94), §7.2; `tasks.md`
> T-4731. **Без коммитов/деплоя; правки — только тесты.**

## Fingerprint

- HEAD: `4a6603bcee569bd8080a852ad65b8ea5400ef582` (base 2.58.48; B+C…H в дереве)
- Scope sha256 (22 изменённых/новых исходников+тестов, финальный):
  `cc5f9fd4817a577df31810a339a62400ea8f7d8718c17390408a432258698c11`
- Environment: `win32-py312-venv`, `node v24.16.0`

## Изменённые файлы/компоненты

| Файл | Что |
|---|---|
| `tests/test_mca06_sleep_i_round1037.py` (new) | T-4731: 10 тестов / 8 детерминированных fixture-сценариев (S1–S5 + unchanged + идемпотентность); каждый проверяет статус + durable отчёт §7.2 (`report_json`, 8 групп) |
| `tests/test_mca01_tx_task_supervisor_round1027.py` | allowlist write-точек `database.py` 155→**159** (+4 commit `_migrate_dream_runs_v25`, L-MCA14-3) |
| `tests/test_mca05_episodes_stories_round1027.py` | `_SCHEMA_VERSION_STORIES_MARK` → tail **v25** (`_SCHEMA_VERSION_DREAM_RUNS`), конвенция волн |
| `tests/test_summary_run_store_asap41.py`, `tests/test_summary_source_window_asap41.py` | fresh-init `user_version` pin 24→**25** (импорт `_SCHEMA_VERSION_DREAM_RUNS`) |

## Сценарии (spec §9.1; seed/фикстуры детерминированы)

| # | Сценарий | Статус | Отчёт §7.2 |
|---|---|---|---|
| S1 | слабые якоря (2 пересказа 1 события, tg=7) | `insufficient_evidence` | independent=1, found=2, written=0 |
| S2 | 2 независимых первичных якоря (tg=1,2) + мост | `written` | written=1, independent=2, bridge_ok=1, llm.calls=1; A14: chain → `{1,2}` |
| S2b | мост валиден, нового вывода нет (`{"paradigms":[]}`) | `unchanged` | written=0, independent=2, llm.calls=1 |
| S3a | «раньше» (200д) строго раньше «сейчас» | `written` | date_ranges.max=anchor_ts, bridge_ok=1 |
| S3b | обратный порядок (anchor свежее периода) | `insufficient_evidence` | written=0, independent=2, trace reason=time_order |
| S4a | cooldown завершённого прогона | `cooldown` | written=0, run.manual=False |
| S4b | backoff ошибок (streak=1, нет новых данных) | `cooldown` | detail=backoff |
| S5a | per-chat квота (used=1≥limit) | `budget` | written=0; resolver detail=per-chat |
| S5b | глобальный кап (per-chat=0, global=30) | `budget` | written=0; resolver detail=global |
| R | повтор той же фикстуры | `duplicate` | written=0, счётчик парадигм не растёт |

## Команды и результат

| Команда | Результат |
|---|---|
| `py_compile` 24 файла (исходники+тесты) | PASS (exit 0) |
| `pytest tests/test_mca06_sleep_i_round1037.py` | **10 passed** |
| `pytest` 5 файлов mca-06 (bc/de/fg/h/i) | **118 passed** |
| `pytest` полный (detached, `-q -rf --tb=line`) | **11287 passed / 6 failed** / 1 warning, 391.34s |
| `pytest` 4 затронутых пинами файла (после правок) | **131 passed** |
| `node --test tests/js/*_test.js` | **55/55 pass**, 0 fail |
| `python tools/gen_param_registry_round1025.py --check` | **CHECK OK, реестр 488** (exit 0) |
| `node --check web/app.js` | OK (exit 0) |

## Failed-классификация (6 падений полного прогона)

**Все 6 — дрейф version-pin от санкционированного DDL v25, НЕ web/-bounds и
НЕ новые поведенческие регрессии:**

1–5. `test_mca05_episodes_stories_round1027.py::TestMigrationV21`
(`test_v21_tables_and_user_version`/`_idempotent_reinit`/`_registry_order_and_checksum`)
+ `test_summary_run_store_asap41.py::test_v24_migration_fresh_db_three_tables`
+ `test_summary_source_window_asap41.py::test_v24_migration_fresh_db` — `assert
user_version == 24`, фактически **25** (v25 `_migrate_dream_runs_v25`, D5).

6. `test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer`
— allowlist `database.py` 155, фактически **159** (+4 commit v25-миграции; все
внутри `_migrate_dream_runs_v25` → guarded по `func.name.startswith("_migrate_")`;
`unguarded == []`).

**Резолюция (тест-онли):** 4 файла обновлены на актуальный tail/allowlist v25
(конвенция волн/реестра mca-14, L-MCA14-3). Точечно **131 passed**; новые
поведенческие падения не обнаружены.

## Недоступные/отложенные проверки

- Повторный ПОЛНЫЙ pytest после тест-онли правок не запускался (правило
  «один полный прогон» + targeted-rerun): эффективный ожидаемый итог —
  **11294 passed / 0 failed** (11287 + 6 исправленных пинов + 1 сценарий
  unchanged), подтверждён точечно по всем 6 пинам и по mca-06 i-файлу.
- Прод-прогон / deploy / T-4733 — вне scope (waves).

## Остаточный риск

- `NOW` в фикстурах — модульный `int(time.time())`; cooldown/backoff сравнивают
  реальные часы прогона, но окна (20ч/1ч) много больше времени теста — флака
  не вносит; бюджет-счётчики замоканы.
- При следующей волне DDL хвост реестра снова сдвинет эти пины — конвенция
  осознанная (mca-14 реестр).


---

# mca-06-sleep-paradigms — Evidence (Rework M-1/L-1/L-3, review T-4732, round 10.38)

> Устранение findings финального review (`review.md`): [M-1] Medium-blocking
> (отчёт §7.2 «причины отсева» не заполнялись), [L-1] dedicated OFF-тест
> `MCA_DREAM_HISTORICAL_PROFILE_ENABLED`, [L-3] сохранение/документирование
> мэппинга `unchanged→empty`. **Без коммитов/деплоя.**

## Fingerprint

- HEAD: `4a6603bcee569bd8080a852ad65b8ea5400ef582` (base 2.58.48; все блоки в дереве)
- Scope sha256 (4 изменённых в rework: worker + 3 тест-файла):
  `7b2a77134a0c098e8071cd600431a79ea99bfe60433fabe5631a9a97720a41c7`
- Environment: `win32-py312-venv`

## Изменённые файлы/компоненты

| Файл | Что |
|---|---|
| `services/dream_worker.py` | `_run_deep_once_core`: `reject_reasons` writer — профильные `excluded_young`/`duplicates` (из `HistoricalSelection`) + аккумуляция `bv.reason` мост-валидатора; `_rep(...reject_reasons...)` перед ранним `insufficient_evidence`; `_deep_report_json` потребитель уже читал ключ. Только отчёт, пайплайн-вердикты не изменены |
| `tests/test_mca06_sleep_fg_round1035.py` | `_Sel` +`excluded_young`/`duplicates`; `test_report_profile_reject_reasons` (M-1); `test_profile_off_uses_legacy_rag_channel` (L-1) |
| `tests/test_mca06_sleep_i_round1037.py` | `test_s3_reject_reasons_in_report` (M-1: 2 отказа `no_subject`/`time_order`) |
| `tests/test_mca06_sleep_bc_round1033.py` | `test_unchanged_maps_to_empty_but_raw_distinct` (L-3, freeze) |

## M-1 — что теперь пишется в §7.2

`report_json.anchors.reject_reasons` заполняется двумя writers'ами:
- профиль (`MCA_DREAM_HISTORICAL_PROFILE_ENABLED` ON): `excluded_young`,
  `duplicates` (только ненулевые; `missing_timestamp` — как отдельная 7-я
  группа, без дублирования);
- мост-валидатор (`MCA_DREAM_EVIDENCE_TYPING_ENABLED` ON): счётчики по
  `bv.reason` (`unresolved_source`/`time_order`/`no_subject`/`no_bridge`).

`_rep` с полным `reject_reasons` вызывается до раннего `insufficient_evidence`,
поэтому отчёт не теряет причины, даже когда отклонены все кандидаты.
`_deep_report_json` cap ≤10 ключей и R17-safe (только коды/счётчики).

## L-1 / L-3

- **L-1:** OFF-тест `test_profile_off_uses_legacy_rag_channel` — при рубильнике
  OFF вызывается legacy `get_rag_facts` (2 старых якоря → `written`);
  `select_historical_candidates` не вызывается (`retrieve_calls=0`).
- **L-3:** `_DEEP_REASON_MAP["unchanged"]=="empty"` не менялся (паритет OFF);
  тест `test_unchanged_maps_to_empty_but_raw_distinct` фиксирует, что raw-лог
  `unchanged` ≠ `duplicate`. UI-метка `unchanged` — зона mca-17c (вне scope).

## Команды и результат

| Команда | Результат | Evidence ID |
|---|---|---|
| `py_compile` worker + 3 теста | PASS | `7b2a7713…` |
| `pytest` bc1033 + de1034 + fg1035 + h1036 + i1037 | **123 passed** (`-q`; согласование round-2: 36+39+26+11+11) | `7b2a7713…` |
| `pytest` 5 mca-06 + deep_sleep + dead_extractor_round1024 + sleep_manual_round1018 | **220 passed** | `7b2a7713…` |

## Недоступные/отложенные проверки

- Полный pytest повторно не гонялся (правило «один полный прогон» + targeted);
  правка — только writer отчёта + тесты, вердикты пайплайна не тронуты.
- Прод-прогон / deploy / T-4733/T-4734 — вне scope (waves). [M-2] — doc-only
  (@Architect), [L-2] — текст spec/ADR при release-коммите.

## Остаточный риск

- Нет нового: изменённый путь — только формирование bounded-отчёта; assert
  `set(rep)==REPORT_GROUPS` (8 групп) сохранён, OFF-паритет отчётов не задет
  (`MCA_DREAM_RUN_REPORTS_ENABLED` OFF → writer не вызывается).




