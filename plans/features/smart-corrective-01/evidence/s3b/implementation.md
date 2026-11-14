# SMART-CORRECTIVE-01 — S3B-INPUT implementation evidence

Статус: **REVIEW** (кандидат для независимого ревью; не VERIFIED).
Дата: 2026-11-14.

## Идентичность кандидата

- Epic: `smart-corrective-01`, срез `S3B-INPUT`.
- Базовая линия: ветка `sc/corrective-s4` @ `7c1e1afb` (production-код
  S1/S2/S3 = `163b8ddd`, S4 code candidate = `8ccd0730`; release line
  `release/2.58.200` @ `13884daa` = deployed `0e4a144d`).
- Рабочая ветка: `sc/corrective-s3b`.
- Code candidate commit: `6d43e3c318299846e42b35d8ae96ea85d2182327`
  (`fix(checkup): capacity-aware significant-fact input assembly (S3B)`).
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-21b619c2`
  (managed `WorkspaceData/worktrees`, registered как `s3b-input`).

## Изменённые файлы

Production:

- `services/checkup_service.py` — единственная точка сборки user-payload
  чекапа:
  - `_InputBudget` + `_resolve_input_budget()`: ФИЗИЧЕСКАЯ ёмкость модели
    (`services.model_capacity.resolve_capacity` → реальное окно; минус
    `count_tokens(system)`, `count_tokens(tool schemas)`, ответ
    `compute_available_budget` и один раунд tool-результатов
    `output_reserve_tokens`) отделена от ОПЕРАТОРСКОГО предела
    `limits.checkup_max_input_symbols`, который действует только при
    effective `flags.budgets_enabled=true` (`services/budget_gate`).
  - `_assemble_input()`: раскладка по значимости (0 — сбои/причины отказа/
    traceback/структурные факты и провенанс; 1 — warning/degraded; 2 —
    обычный INFO-поток). Строки не режутся посередине; при переполнении
    остаётся подмножество целых строк в исходном порядке, а опущенное
    считается и помечается `[checkup-input-truncated]` с `omitted_lines`,
    `omitted_chars`, `partial_lines`, `basis`, `remainder=not_pushed` и
    маршрутом `continuation=inspect_runtime:time_window,cursor`.
  - `_head_prefix()`: единственный честный случай частичной строки — когда ни
    одна строка секции не влезает целиком (срез по тому же токенному
    счётчику, без новых констант).
  - `_metrics_section()`: единственная форма обёртки `<memory_health>`;
    фиксированный клип `_METRICS_MAX_SYMBOLS=2000` УДАЛЁН — секция метрик
    участвует в общей ёмкости, а не отнимает бюджет логов скрытой
    константой.
  - `_HISTORY_NOTE`: при наличии провенанса `[log-source]` и реального
    runtime-инструмента payload сообщает, что окно наблюдения — свежий
    срез и не запрещает исторический запрос (`time_window` для
    событий/проб, `cursor` для продолжения выдачи), при этом честно
    оговаривает, что сырой текст старше окна в этом запуске повторно не
    читается.
  - `_has_runtime_tool()`: обещание продолжения даётся только когда в
    схемах реально есть существующий `inspect_runtime`.
  - телеметрия прогона расширена (старые ключи сохранены): `input_chars`,
    `input_tokens`, `input_omitted_lines`, `input_budget_basis`,
    `input_budget_chars`, `input_budget_tokens`, `input_window`,
    `input_window_source`, `budgets_enabled`, `report_length_setting`.
  - `limits.checkup_max_symbols` по-прежнему только подставляется в
    `{max_symbols}` system-промпта и НЕ участвует в размере payload и
    исследовании.
- `config/settings.py` — ТОЛЬКО комментарии к `CHECKUP_MAX_SYMBOLS` /
  `CHECKUP_MAX_INPUT_SYMBOLS` (семантика и приоритет budgets). Значения,
  дефолты и способ чтения не изменены; сохранённые значения владельца не
  перезаписываются. В брифе write-scope указан `services/settings.py`;
  фактический модуль настроек проекта — `config/settings.py` (другого
  `services/settings.py` в репозитории нет).

Тесты:

- `tests/test_smart_corrective_input.py` (NEW, 16 тестов) — контракт §7
  (см. row mapping).
- `tests/test_checkup_service.py` — обновлены ровно 4 теста, кодировавших
  старое поведение «обрезать ровно N символов без следа»:
  `test_input_truncated_with_warning`,
  `test_long_logs_metrics_survive_within_limit`,
  `test_disabled_or_no_db_no_metrics_section` (бывший
  `test_disabled_or_no_db_byte_identical_old_behavior`),
  `test_truncation_warning_honest_numbers`. Остальные 21 тест файла не
  менялись.
- `tests/test_selfdiag_corrective_research.py` — real-path тесты читали
  фиксированный диапазон строк `[150,175]` файла `services/checkup_service.py`
  и ломались от любого законного изменения размера файла. Введён
  `_candidate_line()` (поиск якоря `if telemetry is not None` в байтах
  кандидата); проверка «real router читает реальные байты» сохранена, но
  больше не зависит от номера строки.

## Что именно проверяется (наблюдаемый контракт)

Таксономия §7.1 (7 видов) и владельцы:

| № | Вид ограничения | Владелец / поведение после среза |
|---|---|---|
| 1 | Окно наблюдения журналов | `services/system_logs_fetcher` (свежий срез). Payload с `[log-source]` + реальный tool-loop объявляет исторический маршрут; окно историю не запрещает |
| 2 | Полнота диагностических данных | `services/diagnostic_collector` (facts/`not_checked`/`reason_code`). Строки фактов — приоритет 0, сохраняются первыми |
| 3 | Физическая ёмкость модели | `services/model_capacity`: реальное окно минус system, tool schemas, раунд tool-результатов, ответ |
| 4 | Операторские бюджеты | `services/budget_gate` → `limits.checkup_max_input_symbols`; только при budgets ON |
| 5 | Размер отдельной порции | потолки fetcher/probe (строки/байты) + по-секционные маркеры; `[facts_budget_exceeded]` сохраняется |
| 6 | Желаемый объём отчёта | `limits.checkup_max_symbols` → ТОЛЬКО `{max_symbols}` промпта |
| 7 | Лимиты канала доставки | `send_chunked_reply` (outbound), не вход; не менялся |

Поведение при переполнении:

- факты/состояния источников/причины отказа/traceback/CRITICAL сохраняются;
- строки остаются целыми и в хронологическом порядке; частичная строка —
  только когда целая не влезает вообще;
- опущенное явно посчитано (`omitted_lines`, `omitted_chars`), payload
  честно помечен и называет маршрут дальнейшей диагностики либо его
  отсутствие (`continuation=not_available_in_this_run`);
- при budgets OFF символьный предел `limits.checkup_max_input_symbols` не
  режет доказательства; физический гвард и no-progress/security-гварды
  остаются;
- новых произвольных числовых констант не введено (единственные числа в
  метке — фактические счётчики; резерв под метку считается из её же текста).

## RED → GREEN

RED (те же новые тесты на pre-fix `services/checkup_service.py`, база
`sc/corrective-s4` @ `7c1e1afb`, интерпретатор `.venv`):

```
py -3 -m pytest tests/test_smart_corrective_input.py -q
=> 15 failed, 1 passed
```

Падения — ровно исходные дефекты: факт за 12k терялся, `[checkup-input-*]`
маркеров/маршрута не было, операторский предел резал и при budgets OFF,
метрики резались на 2000, `_METRICS_MAX_SYMBOLS` существовал, capacity не
учитывалась. Единственный pass — негативная проверка «без tools нет
ложного обещания истории».

GREEN (кандидат `6d43e3c3`, `.venv`, offline fixtures, без production):

```
py -3 -m pytest tests/test_smart_corrective_input.py -q        => 16 passed
py -3 -m pytest tests/test_checkup_service.py -q              => 25 passed
py -3 -m pytest tests/test_smart_corrective_input.py \
  tests/test_checkup_service.py tests/test_checkup_contract.py \
  tests/test_checkup_handlers.py tests/test_selfdiag_corrective_research.py \
  tests/test_smart_corrective_completion.py -q                => 158 passed
py -3 -m pytest tests/test_smart_corrective_input.py \
  tests/test_checkup_service.py tests/test_checkup_contract.py \
  tests/test_checkup_handlers.py tests/test_checkup_prompts.py \
  tests/test_p0_checkup_core_contract.py \
  tests/test_selfdiag_corrective_research.py \
  tests/test_smart_corrective_completion.py tests/test_tool_loop.py \
  tests/test_checkup_logs_fetcher.py tests/test_payload_builder.py \
  tests/test_self_diag_golden.py tests/test_soul1_direct_prompt_reads.py \
  tests/test_unified_core_route_coverage.py -q                => 312 passed
py -3 -m pytest tests/test_mca11_tool_result_round1028.py \
  tests/test_mca11_chain_stages_round1028.py tests/test_agentic_ai_round1020.py \
  tests/test_agentic_events_round1026.py tests/test_mca23_phase2.py \
  tests/test_smoke_round1016_tool_loop.py tests/test_factcheck_service.py \
  tests/test_factcheck_tools_round1020.py tests/test_prompt_readback.py \
  tests/test_tool_schemas.py tests/test_mca19_block_g_round1043.py \
  tests/test_mca20_integration_round1045.py tests/test_direct_chat.py \
  tests/test_asap7_direct_l1.py tests/test_decision_making_round1026.py \
  tests/test_settings_helpers.py tests/test_diagnostic_settings_adapter.py \
  tests/test_param_catalog.py -q                               => 751 passed
py -3 -m pytest tests/test_webapp_api.py tests/test_tool_router.py \
  tests/test_smart_corrective_budget_policy.py \
  tests/test_smart_corrective_source_reader.py \
  tests/test_evol_source_reader.py -q                          => 338 passed
py -3 -m pytest tests/test_settings_helpers.py \
  tests/test_diagnostic_settings_adapter.py tests/test_param_catalog.py \
  tests/test_self_diag_golden.py tests/test_soul1_direct_prompt_reads.py \
  tests/test_unified_core_route_coverage.py tests/test_payload_builder.py \
  tests/test_checkup_logs_fetcher.py -q                        => 211 passed
py -3 -m py_compile services/checkup_service.py \
  config/settings.py tests/test_smart_corrective_input.py      => OK
```

Известные pre-existing падения (те же 9 на чистой базовой линии, подтверждено
в evidence S4; ни один файл не входит в S3B):

```
tests/test_tool_coordinator_round1026.py
tests/test_er65_sent_segment_snapshot.py
tests/test_direct_fallback_recompose_asap32.py
tests/test_diagnostic_probes.py::TestValidation::test_time_window_is_bounded
=> 9 failed, 132 passed (идентично базе)
```

## Row mapping (requirements-map, slice S3B-INPUT)

| req_id | Наблюдаемое доказательство (кандидат) |
|---|---|
| `SC-INP-FIND-01` | `limits.checkup_max_input_symbols` больше не смешивается с физикой: при budgets ON действует как операторский cap (`test_operator_cap_applies_when_budgets_on`), при OFF не режет доказательства (`test_operator_symbol_cap_ignored_when_budgets_off`); сохранённое значение не перезаписывается (`test_saved_values_are_effective_and_not_rewritten`) |
| `SC-INP-FIND-02` | Фиксированный клип метрик удалён (`test_fixed_metrics_clip_removed`, `test_metrics_not_clipped_by_fixed_constant`; секция живёт в общей ёмкости, тег `</memory_health>` сохраняется) |
| `SC-INP-FIND-03` | Обрезка входа по символам заменена раскладкой по значимости: факт за 12k доходит (`test_fact_beyond_old_symbol_limit_reaches_payload`), строки целые и в порядке (`test_lines_kept_whole_and_in_original_order`), частичная строка — только при физической невозможности с honest-маркером (`test_input_truncated_with_warning`) |
| `SC-INP-FIND-04` | `limits.checkup_max_symbols` влияет только на `{max_symbols}` промпта: payload и набор инструментов идентичны при 250 vs 9000 (`test_report_setting_does_not_shrink_research`) |
| `SC-INP-TAX-01` | Окно журнала — отдельный вид: свежий срез + объявленный исторический маршрут при реальном tool-loop (`test_fresh_window_announces_historical_access`); без инструмента обещания нет (`test_no_tools_no_false_promise_about_history`) |
| `SC-INP-TAX-02` | Полнота diagnostics: `DIAGNOSTIC_EVIDENCE`, `reason_code`, `errors_state`, `not_checked` сохраняются как приоритет 0 (`test_fact_beyond_old_symbol_limit_reaches_payload`) |
| `SC-INP-TAX-03` | Физическая ёмкость модели учитывается реально (`_resolve_input_budget`, `test_overflow_packs_by_significance_with_continuation_path`, `test_no_invented_default_cap_when_capacity_unavailable`); резолвер недоступен → потолок не выдумывается |
| `SC-INP-TAX-04` | Операторские бюджеты — существующий `budget_gate.budgets_enabled` (ON/OFF тесты выше); второго рубильника нет |
| `SC-INP-TAX-05` | Размер порции — отдельные потолки владельцев: по-секционные маркеры `section=logs|metrics` с фактическими `omitted_*`; при частичной строке `partial_lines=1` (`test_input_truncated_with_warning`) |
| `SC-INP-TAX-06` | Желаемый объём отчёта — только промпт (`test_report_setting_does_not_shrink_research`) |
| `SC-INP-TAX-07` | Лимит канала доставки остаётся у outbound (`send_chunked_reply`); вход его не наследует (код не изменялся, в evidence зафиксировано) |

## Интерфейс для S6-PROMPT

- Маркеры payload (генерируются сервисом, не промптом):
  - `[checkup-input-truncated] section=<logs|metrics> omitted_lines=.. omitted_chars=.. partial_lines=.. basis=<operator|physical|operator+physical> remainder=not_pushed continuation=<inspect_runtime:time_window,cursor|not_available_in_this_run>`
  - `[checkup-input] journal_window=fresh_slice_only; ...`
- System-промпт S6 может ссылаться на эти маркеры/поведение, но не должен
  дублировать утверждения о доступе к сырому тексту старше окна.
- Сохранить в `checkup_service.py` при правках S6: приоритетные префиксы
  (`[log-source`, `[checkup-input`, `DIAGNOSTIC_EVIDENCE`, `not_checked=`),
  единственную обёртку `_metrics_section`, отсутствие новых фиксированных
  символьных констант, подстановку `{max_symbols}` только в system.
- `tests/test_selfdiag_corrective_research.py` больше не привязан к номеру
  строки — S6 не обязан править числа.

## Ограничения / что осталось за границей среза

1. **REQUIRED FOLLOW-UP (вне write-scope S3B).** `DiagnosticCollector.
   collect_for_checkup` рендерит facts-блок с `max_chars=
   ProbeLimits.max_facts_chars` (env `SELF_DIAG_PROBE_MAX_FACTS_CHARS`,
   default 3000) и дописывает `[facts_budget_exceeded]`. Это отдельный
   chunk-size потолок коллектора (вид 5), не старые чек-лимиты; маркер
   честный, полный bundle доступен tool-loop через `inspect_runtime`.
   При этом сам `render_facts_text` документирует `max_chars=0` как
   «искусственного бюджета нет» — call-site расходится с этим контрактом.
   Требуется решение PM: либо привести call-site к capacity/budgets-политике
   (файл `services/diagnostic_collector.py`), либо зафиксировать 3000 как
   осознанную операторскую политику. S3B это не исправляет (файл вне
   write-scope), дефект не скрыт.
2. Потолки фетчера (`_MAX_LOG_SYMBOLS=20000`, `_MAX_LOG_LINES=300`) — вид 1/5
   у своего владельца (`services/system_logs_fetcher.py`); входной сборщик их
   не дублирует и не расширяет. Провенанс `window/read/matched/state`
   сохраняется в payload.
3. `resolve_capacity` в боевом пути может обращаться к каталогу провайдера
   (таймаут 2 с, TTL-кэш 24 ч/300 с, существующее поведение
   `services/model_capacity`); в тестах адаптер замокан, production не
   затрагивался.
4. При неизвестной модели окно — планировочные 1 000 000 (существующий
   resolver, `estimated_unknown`), поэтому физический гвард слабее реального
   до первого provider-catalog резолва; при budgets ON операторский cap
   ограничивает вход.
5. Outbound-доставка (вид 7) не менялась: `send_chunked_reply` уже делит
   отчёт и не теряет части; правок в этом срезе нет.
6. Production effective-state не перечитывался (правило среза: без доступа
   к production). Сохранённые значения владельца (по аудиту
   `plans/docs/prod-params-audit-2026-09.md` —
   `limits.checkup_max_input_symbols=40000`) не перезаписываются: код читает
   `hot.get` и ничего не пишет.
7. Админка/реестр docs: ключ `limits.checkup_max_input_symbols` не имеет
   текстового описания в коде (только PG-ключ), поэтому синхронизация
   документации выполнена комментарием в `config/settings.py` и этим
   evidence. Если PM считает нужным обновить внешний реестр параметров —
   отдельный docs-пункт, не код.

## Housekeeping

- Probe-прогоны: `WorkspaceData/runs/.../probe-1f2c3879e9` (пробы payload и
  capacity) закрыты после снятия результатов.
- Worktree сохранён для независимого ревью (retention:
  `evidence/s3b/cleanup-retention.json`); после ревью и переноса evidence
  может быть закрыт штатным `unit-close`.
