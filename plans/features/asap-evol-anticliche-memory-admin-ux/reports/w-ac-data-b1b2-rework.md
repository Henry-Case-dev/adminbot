# AC-DATA — исправление блокеров B1/B2 (Builder rework)

- Кандидат-основа: `4e470cf74636a71e4debf9041c0c7a078fcbd8d1` (ветка `feat/ac-data-sources`,
  база `a9f326f8`) — вердикт ревью `reports/w-ac-data-review.md`: **Needs Fixes** (B1, B2).
- Правка: только два сервиса + набор AC-DATA. Новых таблиц, второго транспорта,
  новых agentic-типов событий и изменений `plans/` (кроме этого отчёта) нет.

## B1 — ложные «версия 0 / 0 правил» на ранних выходах `refresh` (AC-INV-08, §1 п.8)

`services/anticliche_worker.py::_refresh_impl`: действующий банк читается **до** обоих
гейтов (`stored = anticliche_cache.fetch_cache(pg)` → `current_version`, `current_rules`),
оба ранних выхода собираются из него же (`**bank`), а Stage A переиспользует уже
прочитанное (лишнего запроса нет).

Что теперь отдают гейты при банке v9 с 1 правилом:

| Гейт | было | стало |
| --- | --- | --- |
| kill-switch OFF (`DYNAMIC_ANTICLICHE_ENABLED=false`), `force=True` | `status=disabled, version=0, rules=null` → эндпоинт `version=0, rules=0` | `status=disabled, version=9, rules=1, count=0` |
| freshness-skip (`force=False`, свежий `fetched_at`) | `status=fresh, version=9`, ключа `rules` нет → эндпоинт `rules=0` | `status=fresh, version=9, rules=1, count=0` |

Банк при этом не меняется (тесты проверяют `cache_row` после вызова). Транспорт/LLM на
гейтах не вызываются. При полностью недоступном PG поведение прежнее: `fetch_cache`
fail-open → `0` (тот же контракт, что и в основном пути; «неизвестно» выражается через
`anticliche_cache.read_active_version` → `unavailable`, это не менялось).

## B2 — событие проверки не идентифицировало источник и probe (M071, §2.1/§4.4)

`services/anticliche_sources.py`:

- `check_source` замеряет длительность реальной попытки (`time.monotonic`), `_finish`
  пишет `duration_ms` (`None` = ещё не измерена, не «0 мс»); добавлен честный флаг
  `manual` (ручная проверка ≠ автоопрос).
- `emit_check_event(check, *, trace_id=None)` — поля события `mca_events`:
  `component=anticliche`, `stage=source_check`, `status`, `outcome`, `level`,
  `operation_id=check_id`, `attempt`, `reason_code`, `duration_ms`,
  `entity_id=<source_id>`, `entity_ids=[<source_id>]`, `trace_id=<run_id>`,
  `source_ref_json={source_id, transport, http, revision, changed, unchanged,
  content_status, docs_fetched, docs_parsed, bytes, chars, error_code, manual}`.
  Всё — R17-safe (коды/числа/идентификаторы, без тел документов), через существующий
  `build_event`/`flush_events` (`mca_events`), без второй таблицы и второго логгера.
- Второй (агентный) emit `ANTI_CLICHE_SOURCE_CHECK` **удалён**, а не оставлен «тихим
  no-op»: типа нет в закрытом `AGENTIC_EVENT_TYPES`, поля `http/docs/failures` не входят
  в whitelist, поэтому вызов не эмитил ничего. Регистрация нового agentic-типа — отдельное
  решение по enum (`tests/test_agentic_events_round1026.py` фиксирует состав enum), в этот
  багфикс не входит.
- `trace_id` проезжает через `check_sources(..., trace_id=...)` и
  `AntiClicheWorker.check_one(..., trace_id=...)`; AC-PIPE передаёт `run_id` прогона.

Проверено реальным событием (банк/транспорт не PG, хранилище — штатный `DatabaseService`
+ `mca_events.flush_events`, т.е. тот же путь записи):

```text
stage=source_check status=available outcome=success trace_id=run-42
operation_id=620ba0558afb48c0 duration_ms=30 entity_ids=["test-wiki"]
source_ref_json={source_id: test-wiki, http: 200, revision: 65f7a674e485…,
                 changed: true, unchanged: false, docs_fetched: 1,
                 docs_parsed: 1, bytes: 296, chars: 47, manual: true,
                 transport: http, content_status: parsed, error_code: ""}
```

## Тесты

`tests/test_anticliche_sources_ac_data.py` — 4 новых теста (итого 66):

- `TestRefreshGatesReportRealBank::test_disabled_kill_switch_reports_real_bank` —
  kill-switch OFF при банке v9/1 правило: `version=9`, `rules=1`, `count=0`, транспорт не
  вызван, банк не тронут.
- `TestRefreshGatesReportRealBank::test_fresh_skip_reports_real_rule_count` — свежий
  `fetched_at`, `force=False`: `status=fresh`, `version=9`, `rules=1`, ни fetch, ни LLM.
- `TestCheckEventHistory::test_stored_event_identifies_source_and_probe` — реальная проверка
  → `emit_check_event` → `flush_events` → SELECT: проверяются сохранённые
  `stage/status/outcome/operation_id/trace_id/entity_ids/duration_ms` и поля
  `source_ref_json` (`source_id`, `http`, `changed`, `unchanged`, `docs_*`, `bytes`,
  `manual`); длительность измерена (транспорт с задержкой 20 мс → `≥10`).
- `TestCheckEventHistory::test_stored_event_marks_unchanged_revision` — проверка без нового
  содержимого (`unchanged`): `outcome=success`, `unchanged=true`, `changed=false`,
  сохранена подтверждённая ревизия; `trace_id` не выдуман.

### Мутации (доказательство, что тесты ловят именно эти дефекты)

| Мутация | Результат |
| --- | --- |
| disabled-ветка возвращает `version=0, rules=0` (как в 4e470cf7) | RED: `test_disabled_kill_switch_reports_real_bank` (`assert 0 == 9`) |
| fresh-ветка возвращает `{version, source}` без `rules` (как в 4e470cf7) | RED: `test_fresh_skip_reports_real_rule_count` (`KeyError: 'rules'`) |
| `emit_check_event` без `source_ref_json`/`entity_ids`/`entity_id` (как в 4e470cf7) | RED: оба теста `TestCheckEventHistory` |
| убрано измерение `duration_ms` в `_finish` | RED: `test_stored_event_identifies_source_and_probe` (`None >= 10`) |

Все мутации откатаны правкой текста; рабочее дерево после — только целевые файлы.

## Прогоны (кандидат этого отчёта)

- `pytest tests/test_anticliche_sources_ac_data.py -q` — **66 passed** (было 62).
- Затронутые области: `test_anticliche_cron_limit_round1024`, `test_anticliche_round1023`,
  `test_anticliche_semantics_round1025`, `test_anticliche_sources_ac_data`,
  `test_hotfix3_anticliche_report_round1025`, `test_pg_db`,
  `test_budget_data_repair_round1024`, `test_budget_global_toggle_round1024`,
  `test_budget_guardrails_round1024`, `test_budget_overrides_merge_round1024`,
  `test_round1025_f8_registry`, `test_external_log_round1024` — **361 passed, 0 failed**
  (было 349 + 4 новых + 8 из cron-limit-модуля).
- Контракт событий/воркеров (два прогона): `test_agentic_events_round1026`,
  `test_mca13_event_contract_round1027`, `test_mca17a_observability_core_round1027`,
  `test_anticliche_sources_ac_data` — **212 passed, 1 failed**; `test_mca17_sleep_memory_workers_round1050`,
  `test_mca01_tx_task_supervisor_round1027`, `test_add_exp_expression`,
  `test_soul1_style_policy` — **173 passed, 1 failed**. Итого 385 passed, 2 предсуществующих
  падения (см. ниже), ни одного нового.
- Предсуществующие падения (не относятся к правке, файлы не в диффе этой ветки):
  `test_mca17a...::test_registry_event_names_exist_in_code` (`mca07_answer_cache` — реестр
  процессов) и `test_mca01_tx_task_supervisor_round1027::test_write_points_go_through_single_writer`
  (дрейф аудита write-точек: `database.py 217 vs 207`, `prompt_release_policy.py`).
  Оба падают на кандидате `4e470cf7` без этой правки (файлы `mca_process_registry.py`,
  `database.py`, `prompt_release_policy.py` в диффе ветки отсутствуют — `git diff a9f326f8` пуст).

## Что осталось вне пакета

- `T-SRC-CONCURRENCY` (`cron` + manual не создают конкурирующих публикаций) для AC-DATA —
  **UNVERIFIED**: в `refresh` нет single-flight-замка, `max_instances=1` APScheduler не
  покрывает manual+cron, теста нет. Естественный владелец — AC-API (мутации/single-flight);
  дублирование правил исключено дедупом в `_normalize_stored`, теряется вклад одного прогона.
- Полный LLM-анализ/публикация snapshot/UI — AC-PIPE/AC-UI, здесь не проверялись.
