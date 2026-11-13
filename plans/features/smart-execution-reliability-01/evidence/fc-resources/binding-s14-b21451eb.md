# S14-FC-RESOURCES — binding evidence (candidate b21451eb)

Срез: `S14-FC-RESOURCES` (FACTCHECK-REQUEST-INTEGRITY v2 §5–§6/§10.4/§13.3,
SMART-EXECUTION-RELIABILITY-01, wave8).
База среза: `c00caf62` (merge S13 `ffe417d0` + S1 `8fc8b534`).
Код-кандидат: `b21451eb` (ветка `smart/fc-s14-resources`).
Источник: `plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2-full.md`
(sha256 `767baf0a…dc7a`), строки 429–684, 900–984, 1253–1292.
Покрытие: 18 req_id / 161 строка карты (`items` 72 + `additional_requirements` 89).

## 1. Что изменено

| Файл | Изменение |
|---|---|
| `services/factcheck_planner.py` | `FactcheckLimits` + async/sync резолвер (master S1 → chat → global → default), новые заводские 120/600/24/64/100 000/20/32; OFF снимает бюджеты; run_retrieval исполняет по содержательным состояниям; 100k — порция без потери хвоста; снят cap 12 evidence refs и план больше не режется 12/64; 20 результатов на страницу |
| `services/temporal_factcheck.py` | `decompose_claim` 32-частными порциями без хвоста (было 8); `search_queries_for` без скрытого cap 2 (ON — общий 64, OFF — без cap) |
| `tests/test_factcheck_resources.py` | новый durable CONTRACT-набор, 19 тестов |
| `tests/test_factcheck_fc_r1_fix.py` | обновлена 1 старая ассерция, кодировавшая удалённый cap “2 запроса” (противоречила owner §6.4) |
| `services/param_catalog.py` | **не менялся**: аудит показал, что `limits.factcheck_*` там не объявлены; новых admin-ключей/панелей не создано |

Зависимость S1 (`c00caf62`) содержит `budget_gate.BudgetState`/`resolve_budgets`
(last-known-valid, provenance). Фактчек не вводит второй master-выключатель.

## 2. Аудит всех источников ограничений (SFC-5-08)

Сырые данные: `raw/audit-deployed-d20a7f73.json` (deployed-линия),
`raw/audit-candidate-b21451eb.json` (кандидат), `raw/audit-base-head.json`
(S13+S1 до изменений). Скрипт: `raw/audit_caps.py`.
Сравнение deployed `d20a7f73` → база: константы factcheck не менялись (0
расхождений), поэтому deployed-значения = текущие до S14.

| Источник | Где (deployed → candidate) | Было | Стало/effective | Применение |
|---|---|---:|---:|---|
| Python base budget | `factcheck_planner.py:1254` → `:1301` `_BUDGET_SECONDS_DEFAULT` | 10.0 | 120.0 | `_budget_seconds()` (ON) |
| Python max budget | `:1256` → `:1303` `_BUDGET_SECONDS_MAX` | 45.0 | 600.0 | cap адаптива (ON) |
| Python refine cap | `:1258` → `:1305` `_REFINE_CALLS_DEFAULT` | 3 | 24 | `run_retrieval` (ON) |
| Python total queries | `:147` → `:153` `_MAX_QUERIES_TOTAL_DEFAULT` | 12 | 64 | `FactcheckLimits.total_queries` |
| Python search text | `:1250` → `:1297` `_SEARCH_TEXT_BUDGET_CHARS` | 8000 | 100_000 (порция) | `_text_portions` |
| Python page size | `run_retrieval(max_rows_per_query=4)` → `:1925` `None` + limits | 4 | 20 | `evidence_refs_from_search` |
| Python claim units | `_CLAIM_UNITS_HARD_CAP=16` → `_CLAIM_UNITS_PORTION=32` (`:620`) | 16 (жёсткий) | 32 (порция, без обрезки) | `build_claim_units` |
| Python primary fetch | `_MAX_PRIMARY_FETCHES=2` → limits (`:155`) | 2 | 2 ON / без cap OFF | `run_retrieval` |
| Python excerpt | `_EXCERPT_MAX_CHARS=600` → limits (`:156`) | 600 | 600 ON / без обрезки OFF | `fetch_primary_evidence` |
| Python evidence refs | `_MAX_EVIDENCE_REFS=12` (`_assemble`) | 12 | **снят** | `_assemble` |
| Python legacy helpers | `adaptive_query_budget`, `_max_queries_total`, `_refine_calls_limit` | 3/12/hot | **удалены** | второй источник cap устранён |
| param catalog | `param_catalog.py` — нет ни одного `limits.factcheck_*` | нет | не добавлялись | ключи читаются hot/PG напрямую |
| hot configuration | 9 ключей `limits.factcheck_*` (`factcheck_planner.py:1328-1336`) | defaults 10/45/3/12/… | defaults 120/600/24/64/100000/20/32/2/600 | async + sync резолвер |
| env | `FACTCHECK_PIPELINE_V2_ENABLED`, `BUDGETS_ENABLED` | module switch | module switch; бюджеты — S1 master | не новый master фактчека |
| сохранённые значения | `worker_settings.resolve_setting_with_source` (chat→global→default) | читались частично | читаются все 9 ключей + master | `sources[(key)]` |
| cached settings | `hot_config` (ConfigCache) | sync | `resolve_factcheck_limits_sync` для планирования; исполнение — async | per-chat не теряется |
| legacy aliases | `_SEARCH_TEXT_BUDGET_CHARS`/`_BUDGET_SECONDS_*`/`_REFINE_CALLS_DEFAULT` сохранены как имена с новыми значениями | 8000/10/45/3 | 100000/120/600/24 | monkeypatch-совместимость |
| fallback helpers | `_hot_number` (только `resolve_retrieval_budget` без limits), `_limits_from_values` (floor/cast) | 10/45 | OFF → `None`, ON → новые; floor только ≥0/≥1 | fail-open |
| прямые аргументы | `run_retrieval(max_rows_per_query, budget_seconds, refine_calls)`, `execute_retrieval`, `search_queries_for(max_queries)` | 4/10/3/2 | явный аргумент = политика вызывающего; по умолчанию limits | тесты/совместимость |
| orchestration | `factcheck_orchestrator.py:1848` `fsp.run_retrieval(plan, aggregator)` | без args | резолвит limits по `plan.chat_id` | штатный путь |
| service fallback | `factcheck_service.py:2620` `tf.search_queries_for(parts, env)` | default 2 | sync-limits: ON 64 / OFF без cap | temporal fallback |
| внутренние clamps | `_text_portions`, `_assemble`, `_claim_units`, `run_retrieval` total/refine/fetch | 8000/12/16/… | нет скрытых потолков; OFF снимает бюджеты | тесты OFF/ON |

Вне S14 (не бюджет фактчека, остаются для следующих срезов и отражены честно):

| Ограничение | Где | Значение | Владелец |
|---|---|---:|---|
| temporal evidence rows | `mca_gates.temporal_max_evidence_per_run()` (`mca_gates.py:2521`), env `MCA_TEMPORAL_MAX_EVIDENCE_PER_RUN` | 20 | S15-FC-EVIDENCE |
| `support[:1200]` в evidence rows | `temporal_factcheck.py:1406,1440` | 1200 | S15 |
| `_server_parts [:4]` | `factcheck_service.py:1420` | 4 | S16-FC-FINALIZE |
| query text length | `_QUERY_MAX_CHARS=200` | 200 | технический предел провайдера (сохранён) |
| provider timeout/retry/SSRF/RBAC | `search_aggregator`, `safe_fetch`, tool-loop S1 | реальные | сохраняются (SFC-5-07) |

## 3. ON-контракт (SFC-5-02/03/06/09)

- Заводские значения фактически применяются: тест
  `test_on_deadline_and_query_budget_are_applied` — 1 claim = 120 c, 2 = 180 c,
  40 = 600 c; 40 частей → ровно 64 попытки (40 базовых + 24 уточняющих), а не
  40+24=88 отдельно. `stop_reason=budget_exhausted`.
- Штатный путь без ручных аргументов:
  `test_normal_path_uses_plan_chat_limits_without_manual_args` —
  `run_retrieval(plan, aggregator)` берёт per-chat 5/30/7 из
  `plan.chat_id`, делает 5 попыток и сообщает `budget_source=chat`.
- 20 результатов на страницу: `test_on_page_size_20_...` — 30 кандидатов →
  ровно 20 evidence refs, провайдер с 3 результатами → 3 (без требования
  «ровно 20»).
- 100 000 символов = порция: 160k текст → `search_text` 100k,
  `search_text_portions` 2, `"".join(portions)==text`,
  `search_text_truncated=True`.
- Сохранённые настройки не перезаписываются: `base=300`, `max=900`,
  `total=100`, `chars=150000`, `page=25`, `portion=64` — все применены,
  `sources[key]=chat|global|default` (тест
  `test_saved_settings_are_preserved_and_provenance_reported`).
- Значения не минимум: простой claim с одним подтверждением завершается
  `stop_reason=sufficient_evidence`, `budget_exhausted=False` (тест
  `test_stop_reason_sufficient_evidence_before_using_all_queries`).
- Фактически исчерпанный бюджет честно виден: `budget_exhausted`,
  `claims_unchecked_due_to_deadline`, `stop_reason`; частичный результат не
  маркируется аварией (SFC-13-03).

## 4. OFF-контракт (SFC-5-05/10)

- `FactcheckLimits(budgets_enabled=False)` → `base_seconds/max_seconds/
  refine_calls/total_queries/search_text_chars/primary_fetches/excerpt_chars =
  None`; `page_size=20`, `claim_portion=32` — структурные размеры порций.
- `test_off_removes_deadline_query_and_char_caps`: 40 частей →
  **80 попыток** (40 базовых + 40 уточнений), `refine_calls=40`,
  `budget_exhausted=False`; 160k текст целиком в `search_text` и
  `search_text_truncated=False`.
- `test_off_has_no_product_deadline...`: медленные запросы (0,02 c) —
  `budget_seconds=None`, 3 базовых + 3 уточнения, без дедлайна.
- `test_off_ignores_saved_old_budget...` и
  `test_off_saved_budget_does_not_enforce_end_to_end`: сохранённые 10 c / 45 c
  / 3 / 12 / 8000 / 4 / 8 / 2 существуют как `chat`, но не ограничивают:
  80 попыток, `budget_seconds=None`, `budget_source=chat` (происхождение
  показано, а не переписано).
- `test_on_fetch_policy_limits_openings_off_has_no_cap`: ON открывает ≤2
  первоисточника (`fetch_skipped_budget`), OFF — все 5; «все 20 документов
  автоматически» не загружаются (страница ≠ автозагрузка).

## 5. Содержательные остановки и наблюдаемость (SFC-6-02/03, 13-03)

`RetrievalOutcome.stop_reason` (машинный, без текстов):

| состояние | значение | тест |
|---|---|---|
| достаточное evidence / ранний успех | `sufficient_evidence` | `test_stop_reason_sufficient_evidence...` |
| нет прогресса (пустая/нерелевантная выдача) | `no_progress` | `test_stop_reason_no_progress_and_provider_failure...` |
| провайдеры недоступны | `providers_unavailable` | там же |
| продуктовый бюджет ON исчерпан | `budget_exhausted` | `test_on_deadline...` |
| технический предел провайдера | `technical_limit` | `test_technical_provider_budget_is_not_product_budget` |
| пути исчерпаны (все попытки без бюджета) | `paths_exhausted` | `test_off_removes...` |
| скрытый enforcement | `unexplained_stop` | заложен как маркер; не возникает на кандидате |

`budget_exhausted` выставляется только продуктовым бюджетом; provider
`cause=budget` даёт `technical_limit` и НЕ маскируется под дедлайн
(`deadline_exceeded` больше не универсальное объяснение).
Новых LLM-вызовов/классификатора сложности не добавлено: расширение идёт по
существующему coverage `_claim_settled`/`refinement_query_for` (SFC-6-02).

## 6. Декомпозиция 32 и хвост (SFC-5-02/6-06)

- `build_claim_units` обрабатывает материал порциями по 32; 40 предложений →
  40 `ClaimUnit` (`c1…c40`), последний текст на месте.
- `decompose_claim` (temporal) — 40 предложений → 40 `ClaimPart`
  (`p1…p40`), `_CLAIM_PARTS_PORTION=32`.
- `search_queries_for` без скрытого cap 2: 10 частей → 10 запросов (OFF/ON);
  явный `max_queries=2` по-прежнему уважается как политика вызывающего.
- Порция не выдаётся за полный материал: план содержит весь хвост
  (`build_retrieval_plan` больше не режет `adaptive_query_budget`), при ON
  исполнение честно останавливается на 64 и отмечает непроверенное.

## 7. Проверки и точные команды

Окружение: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, Python 3.12.

```
pytest tests/test_factcheck_resources.py -q
→ 19 passed in 2.99s

pytest <40 factcheck-related files> -q
→ 821 passed, 1 failed, 4 errors in 43.99s
```

Те же 39 factcheck-файлов базы (без нового файла) на `c00caf62`:
```
→ 801 passed, 2 failed, 4 errors in 45.21s
```
Разница ровно новым durable-набором (19 тестов) плюс один сетевой flaky;
2 failed + 4 errors идентичны на базе (см.
`raw/pytest-focused-base-c00caf62.txt` и
`raw/pytest-focused-final-21451eb.txt`):
- `test_factcheck_fc_r1_fix.py::...test_all_irrelevant_is_honest_failure` —
  сетевой DuckDuckGo-fallback: тест ожидает отказ, живой провайдер отвечает;
  на финальном прогоне прошёл (flaky от сети), на базе падал;
- `test_mca20_rework1_f1_f2.py::...test_evidence_injection...` — pre-existing
  на базе (экранирование `</evidence>`);
- 4 setup-error `test_evol_fc_admission.py` — `PersistentCooldownTracker`
  без `_last` в комбинированном прогоне; на базе те же 4, отдельно файл
  проходит 22/22. Это order-dependent pre-existing, не S14.

S1-регрессии после merge: `tests/test_smart_exec_ab_round1114.py` проходит;
`test_budget_global_toggle/guardrails` дают те же 5 pre-existing на базе
(не связаны с фактчеком).

## 8. RED на базе и GREEN на кандидате

`raw/s14_resource_probe.py` (14 наблюдаемых проверок, без новых API):
- база `c00caf62`: **0/14** — 10 c/45 c/3/12/8000/16 refs, temporal 8,
  скрытый cap 2, нет OFF-контракта (`raw/red-base-c00caf62.json`);
- кандидат `21451eb`: **14/14** (`raw/green-candidate-21451eb.json`).

Покрытие RED: константы, hard cap claim units, temporal tail, temporal queries,
`FactcheckLimits`, OFF-caps, page>4, OFF query cap, OFF char budget.

## 9. Мутации (тест краснеет при возврате скрытого enforcement)

| Мутация | Красные тесты | Лог |
|---|---|---|
| вернуть 8000-char cap | `test_on_search_text...`, `test_off_removes...` | `raw/mutation-1-8000-cap.txt` |
| скрытый `total_limit=12` | `test_on_deadline...`, `test_off_removes...`, `test_off_saved...` | `raw/mutation-2-hidden-total-12.txt` |
| temporal снова 8 частей | `test_temporal_decompose_keeps_tail_beyond_32` | `raw/mutation-3-temporal-8.txt` |
| вернуть evidence-ref cap 12 | `test_on_page_size_20...` | `raw/mutation-4-evidence-ref-12.txt` |

Все мутации откатывались `git checkout --`; рабочее дерево чистое.

## 10. Гигиена diff

- `git diff --check c00caf62 HEAD -- services tests` → пусто
  (`raw/git-diff-check.txt`, exit=0).
- Все изменённые/новые файлы — UTF-8 без BOM, LF
  (`CRLF=0` проверено по байтам).
- `git diff --stat` и `git diff -w --stat` — `raw/git-diff-stat.txt`,
  `raw/git-diff-w-stat.txt`; whitespace-разница только от переиндентации
  тела порционного цикла temporal (поведение покрыто тестами).

## 11. Соответствие требованиям

| req_id | Чем подтверждено |
|---|---|
| SFC-5-01 | аудит §2, `raw/audit-*.json`, RED base (10/45/3/12/8000/16) |
| SFC-5-02 | §3, `test_factory_values...`, `test_on_deadline...`, page/portion тесты |
| SFC-5-03 | §3, `test_stop_reason_sufficient...` (не минимум), §4 (OFF не hard cap) |
| SFC-5-04 | §2 (все слои), `test_all_audit_layers_are_read` |
| SFC-5-05 | §4, `test_off_removes...`, `test_off_has_no_product_deadline...` |
| SFC-5-06 | §3 (saved/higher), §4 (OFF), `coverage_summary` |
| SFC-5-07 | §2 (реальные пределы/provider timeout/RBAC/SSRF), нет нового master, S1 `budget_gate` |
| SFC-5-08 | §2 полная таблица + `raw/audit-*.json` |
| SFC-5-09 | §3/§4 `sources`, `test_saved...`, `test_default_provenance...` |
| SFC-5-10 | §4 `test_off_saved_budget_does_not_enforce_end_to_end` (live postdeploy — residual) |
| SFC-6-01 | §3/§4 (значения не минимум), `sufficient_evidence` |
| SFC-6-02 | §5: existing coverage, без нового классификатора/LLM |
| SFC-6-03 | §5 stop_reason: 7 состояний, без обязательного числа источников |
| SFC-6-04 | §6: нет дублей (existing `attempted_texts`/dedup), explicit caps, без нового агента |
| SFC-6-05 | §3 page 20 / меньшее as-is / `fetch_skipped_budget` / URL≠evidence |
| SFC-6-06 | §6: 32-порции, 40 частей, temporal tail, нет микротезисов |
| SFC-10-04 | §1: только существующие planner/temporal; порядок FC-TRUST→WSQ сохранён; 10/45/8000/4 как инвариант |
| SFC-13-03 | §5: `stop_reason`, budget vs technical vs provider; live — residual |

## 12. Остаточное (postdeploy, не блокирует preprod-review)

1. **Production effective config** (SFC-5-10, SFC-13-03 live): на реальном
   сервере проверить `flags.budgets_enabled` (default ON), отсутствие
   сохранённых `limits.factcheck_*` (или их источник), применение 120/600/24/
   64/100000/20/32 и снятие enforcement при OFF. Код готов; без деплоя это
   `PENDING`.
2. **Реальные провайдеры** (SFC-5-07): сетевые таймауты/rate limits и
   фактическая выдача (меньше 20) — только live; в тестах контролируемые
   заглушки.
3. **SFC-13-03 live postdeploy**: различимость состояний на контрольных
   production-запусках (request/correlation ID, effective budget state,
   source, queries/candidates/opened/claim units/evidence chars, model
   capacity, stop reason, coverage). Существующие `factcheck_run`/coverage
   логи расширены полями outcome; отдельный аналитический раздел не создан.

Владельцу ничего не назначается: §14.3 источника запрещает ждать
естественных событий чата и owner-проверки; всё, что можно проверить
агентами, проверено выше.
