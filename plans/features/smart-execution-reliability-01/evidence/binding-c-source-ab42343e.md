# C1 — SourceReader без скрытых потолков (binding evidence)

Стадия C1 эпика `SMART-EXECUTION-RELIABILITY-01`. Реализация и тесты — Builder,
независимое ревью/приёмка — Reviewer, далее PM/Orchestrator.

* База: `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199), ancestor HEAD = да.
* Ветка: `smart/c-source`; worktree:
  `WorkspaceData/worktrees/c742e4de9e92c489/SMART-EXECUTION-RELIABILITY-01-92d1db8aefb1-1754cefe`.
* Кодовый коммит (CODE_SHA): **`36dd6b232bf2705cc470764a7ab71451c5c49fdf`**
  (rework после Reviewer blocker; предыдущий кандидат `ab42343e`/`7c113d61`).
* Diff vs база: `services/source_reader.py` (+278/−11), новый
  `tests/test_smart_c1_source_reader_limits.py` (26 тестов),
  правки `tests/test_evol_source_reader.py`.
* Границы записи соблюдены: изменены ТОЛЬКО `services/source_reader.py` и его тесты.
  `tool_loop.py`, `direct_execution.py`, композер/сериализатор, `budget_gate.py`,
  `config/settings.py`, `tool_router.py` не менялись. Деплой не выполнялся.

## 0. Rework после Reviewer (blocker SXR-C1-02)

Reviewer (`review-c1-ab42343e.md`) признал SXR-C1-01/03 Verified, а SXR-C1-02 —
FAILED: `LocalSnapshotProvider.read_file` отклонял ЛЮБОЙ файл >2 МБ как
`file_too_large` ДО применения `line_start`/`line_end`, т.е. большой текст был
недоступен целиком.

Исправлено в `services/source_reader.py`:

| Точка | Изменение |
|---|---|
| `LocalSnapshotProvider.supports_ranges = True` | провайдер явно объявляет возможность постраничного чтения; прочие провайдеры (GitHub: transport-лимит) получают прежний вызов |
| `LocalSnapshotProvider.read_file(..., line_start, line_end, page_ok=True)` | oversized-файл не отклоняется: отдаётся запрошенная порция строк |
| `LocalSnapshotProvider._read_page()` | потоковое чтение (память ≤ порции); абсолютные номера строк; CRLF-совместимый срез; `page-truncated` + `next_line_start`; бинарь по всему файлу (`_control_bytes`, тот же порог, что у `decode_source_bytes`); `file_too_large` — только если первая строка порции физически больше предела; диапазон за EOF → `range_empty` |
| `SourceFile.page` | явные метаданные порции (`line_start/line_end/total_lines/portion_bytes/budget_bytes/truncated/next_line_start`) |
| `SourceReader._range_hints()` | диапазон уходит только провайдеру с `supports_ranges`; служебные чтения цепочки (`_service_read_hints`) идут с `page_ok=False` |
| `SourceReader._page_payload()` | payload порции: `line_range` — абсолютные строки файла, `truncation.why="over_portion"`, `limit_source="file_bytes_page"`, `retrievable_remainder_lines`, `next_line_start`, `provenance.page`; `verified` — те же инварианты (commit-pinned байты, `source_kind=file`) |

RED→GREEN блокера (те же тесты, код откачен к `ab42343e`): `7 failed, 1 passed` —
падают все oversized-сценарии (`unsupported/file_too_large` вместо `ok`), а
path-traversal/ADS-негатив зелёный и на базе. После фикса: **26 passed** в C1-наборе.

## 1. Обязательные требования

| ID | Что проверено | Статус Builder | Где доказательство |
|---|---|---|---|
| `SXR-C1-01` | Потолки 6/2/16 и defaults 3/1/8 не ограничивают чтение; произвольной замены нет; цепочка файлов/вызывающих участков/следующих диапазонов читается | готово к ревью (REVIEW) | §3 RED→GREEN, §4 тесты |
| `SXR-C1-02` | File/byte/binary/path safety сохранены; большой текст доступен диапазонами/страницами; весь репозиторий в один ответ не уходит | готово к ревью (REVIEW) | §3, §5 |
| `SXR-C1-03` | Счётчики живут один запрос и сбрасываются; исчерпание предыдущим запросом не ломает следующий | готово к ревью (REVIEW) | §3 (строки 4–5), §6 |

Срез карты: `S3-EVIDENCE`. `VERIFIED`/`DONE` не заявляю — это вердикт Reviewer.

## 2. Что изменено (`services/source_reader.py`)

| Точка | Было | Стало |
|---|---|---|
| `:159-170` | `_MAX_FILES_CEILING=6`, `_MAX_DEPTH_CEILING=2`, `_MAX_REQUESTS_CEILING=16`, `_DEFAULT_MAX_FILES/DEPTH/REQUESTS=3/1/8` | константы удалены; комментарий фиксирует, что потолка нет и какие safety остались |
| `:220` `_env_policy_int()` | — | «явная политика оператора» = только реально заданная env-переменная; отсутствие/мусор/0 = политики нет |
| `:238/243/248` `max_files/max_depth/max_requests` | `_bounded_int(..., ceiling)` | читают только явную env-политику, `0` = искусственного лимита нет |
| `:257` `budget_limits_enforced()` | — | единственная точка чтения effective `flags.budgets_enabled` через существующий `budget_gate.budgets_enabled(chat_id)`; ошибка резолва → `False` (enforcement не включается) |
| `:1734` `SourceReader.run()` | без бюджета | резолвит предикат один раз на запрос (или принимает готовый `budget_enforced`), снимает снимок политики, ставит `network_baseline` |
| `:2613` `_RunState` | только `files_read/not_checked_reason` | + `budget_enforced`, `limit_files/depth/requests`, `network_baseline`, `chain_chars`, `applied_limits()` |
| `:2235` `_followup()` | `depth_left=max_depth()`, `files_read>=max_files()`, обход режется 6/2 | потолки файлов/глубины только из явной политики; цепочка идёт по релевантности (идентификаторы из тела), ограничена объёмом ОДНОГО ответа (одна порция текста ≤ `budget_chars` или `max_file_bytes`); непрошедшие пути остаются в `untried_paths` |
| `:2518` `_payload()` | `not_checked.depth_left = max_depth()` | `depth_left = None`, когда потолка нет; добавлен `not_checked.applied_limits` (0 = лимита нет) |
| `_read_payload()` truncation | только `retrievable_remainder_lines` | + `next_line_start` при усечении — явное продолжение диапазона |
| `_network_calls()`-телеметрия | пожизненный счётчик провайдера | per-request дельта в `network_calls`/`provenance.network_calls`; пожизненный — отдельным полем `network_calls_total` |

## 3. RED → GREEN (сценарии, которые упирались в потолки)

RED снят на базе `d20a7f73` с теми же тестами (код откатан к базе, тесты оставлены):
`12 failed, 6 passed` — падают именно сценарии потолков, safety-тесты зелёные и на базе.

| Тест (`tests/test_smart_c1_source_reader_limits.py`) | База `d20a7f73` | Кандидат `ab42343e` |
|---|---|---|
| `test_more_than_six_files_in_one_request` (9 связанных файлов) | `len(files)=2` | `len(files)=10`, все `verified` |
| `test_depth_ceiling_removed_for_linked_chain` (6 файлов) | `followup=1` | `followup≥5`, `depth_left=None`, `applied_limits={files:0,depth:0,requests:0}` |
| `test_more_than_sixteen_network_calls_in_one_request` (18 файлов) | `network_calls=4` (обрыв по 8/16) | `network_calls>16`, `files=19` |
| `test_previous_request_does_not_exhaust_next_request` | `network_calls=4` (жизнь провайдера) | запрос A >16 вызовов, запрос B с политикой 16 проходит (`ok`) |
| `test_counters_restart_for_each_request` | `files_read=2` | `10`, затем `1` — счётчик на запрос |
| `test_large_text_readable_in_pages` (1500 строк) | нет `next_line_start` | 5 страниц по 300 строк, склейка == исходный файл, каждая `verified` |
| `test_next_line_start_drives_continuation` (400 строк, окно 1200) | нет `next_line_start` | страницы дочитываются до строки 400 |
| `test_single_request_does_not_dump_the_whole_repository` (40 файлов) | нет `chain_portion_limit` | <40 файлов, `untried_paths` непусты, `chain_delivered_chars ≤ limit+64` |
| `test_budgets_off_ignores_explicit_env_policy` | env-потолки всё равно применялись | 10 файлов при `SOURCE_READ_MAX_FILES/DEPTH/REQUESTS=1` |
| `test_budgets_on_without_policy_has_no_factory_caps` | заводские 6/2/16 | 10 файлов, лимиты 0 |
| `test_predicate_read_through_budget_gate` | API отсутствует | OFF/ON/ошибка резолва → OFF, `chat_id` доходит |
| `test_factory_constants_are_gone` | константы есть | констант нет, `max_*()==0` |

Oversized-текст (§C1 440, blocker Reviewer):

| Тест | `ab42343e` (RED) | `36dd6b23` (GREEN) |
|---|---|---|
| `test_initial_range_of_oversized_text_is_readable` (3 МБ, lines 1–200) | `unsupported/file_too_large` | `ok`, `line_range=[1,200]`, точный текст, `next_line_start=201`, `file_total_lines=35000` |
| `test_next_range_of_oversized_text_is_readable` (201–400) | `unsupported` | `ok`, `line_range=[201,400]`, `next_line_start=401` |
| `test_tail_range_of_oversized_text_reaches_eof` | `unsupported` | `ok`, `line_range=[34991,35000]`, `truncated=false` |
| `test_oversized_without_range_returns_first_portion` | `unsupported` | `ok`, первая порция ≤2 МБ, `next_line_start>1`, `file_total_lines=35000` |
| `test_range_beyond_eof_is_honest_not_found` | `unsupported` | `not_found/line_range_beyond_eof` |
| `test_oversized_binary_stays_binary` (3.6 МБ NUL) | `file_too_large` | `unsupported/binary_content` |
| `test_oversized_traversal_and_ads_still_denied` | denied ✅ | denied ✅ (safety не зависела от фикса) |
| `test_followup_does_not_pull_oversized_page` | — | oversized sibling цепочки пропущен, ответ <20 КБ |
| `test_portion_limit_pages_text_and_refuses_oversized_line` | `file_too_large` для любого oversized | текст страницами; `file_too_large` только для одной строки > порции |

Safety-тесты (path traversal, denied paths/ADS, binary, чужой хост,
provenance) зелёные и на базе, и на кандидате — они фиксируют, что удаление
потолков и пейджинг не ослабили безопасность.

## 4. Прогоны (venv `C:\Code\Python\adminbot\.venv`)

Прогоны на `36dd6b23`:

| Прогон | Результат |
|---|---|
| `pytest tests/test_smart_c1_source_reader_limits.py` | **26 passed** |
| `pytest tests/test_evol_source_reader.py tests/test_deploy_identity_d4b.py tests/test_smart_c1_source_reader_limits.py` | **159 passed** |
| `pytest tests/test_evol_source_reader.py tests/test_deploy_identity_d4b.py tests/test_evol_evidence_window.py tests/test_evol_evidence_routing.py tests/test_diagnostic_policy.py tests/test_tool_router.py tests/test_smart_c1_source_reader_limits.py tests/test_checkup_service.py tests/test_p0_checkup_core_contract.py` | **486 passed** |
| `... + tests/test_checkup_contract.py tests/test_checkup_handlers.py tests/test_checkup_logs_fetcher.py tests/test_checkup_prompts.py` | **614 passed** |

RED на предыдущем кандидате (`ab42343e`, тесты новые): `7 failed, 1 passed` по
oversized-сценариям; RED на базе `d20a7f73` для потолков 6/2/16 — `12 failed, 6 passed`
(см. §3 выше).

Предсуществующих падений в этих наборах на базе не выявлено → BACKLOG-записей нет.
Обновлены три легаси-теста, которые утверждали старые заводские потолки:
`test_explicit_file_policy_produces_untried_paths`, `test_depth_ceiling_absent_by_default`,
`test_explicit_request_policy_stops_the_lookup`; автofixture больше не подменяет
`settings.SOURCE_READ_MAX_*` (эти значения не являются политикой).

## 5. Безопасность, которая сохранена

* `max_file_bytes` (2 МБ) — предел ОДНОЙ ПОРЦИИ; oversized-текст читается
  диапазонами/страницами с `next_line_start`. `unsupported/file_too_large` —
  только когда неделимая первая строка порции больше предела.
* `path_is_denied`, `_local_target` (repo-relative, отказ на `..`, symlink, ADS),
  `decode_source_bytes` (UTF-8 strict, NUL/бинарь → `binary_content`);
  для oversized-файла бинарь определяется по ВСЕМУ файлу (тот же порог).
* `SafeFetcher` (SSRF/редиректы/таймаут/байты) и `_classify_http_status`
  (401/403/429 → rate_limit/auth_failed) — без изменений.
* Один ответ не превращается в выгрузку репозитория: цепочка ≤ одной порции
  текста, остаток — `untried_paths`/`next_line_start`; служебные чтения
  цепочки (`page_ok=False`) не тянут мегабайтную порцию.

## 6. Счётчики: где живут и как сбрасываются

* `files_considered/files_read/not_checked_reason/chain_chars` — поля `_RunState`,
  создаётся в `run()` на каждый вызов ⇒ предыдущий запрос их не расходует.
* Сетевые вызовы: `GitHubProvider.network_calls` — пожизненная наблюдаемость;
  enforcement и `payload.network_calls` используют `now − network_baseline`,
  снятый на входе текущего запроса.
* Reader/провайдер по-прежнему кэшируется на `ToolDeps` (утечка соединений не
  вводится) — но кэш больше не несёт исчерпанного ресурса.

## 7. Effective configuration (для acceptance-метаданных)

* Предикат: `flags.budgets_enabled`, `chat → global → settings.BUDGETS_ENABLED`
  (заводски `True`), читается только через `budget_gate.budgets_enabled(chat_id)`.
* В тестах: предикат подменён детерминированно (OFF) кроме тестов, которые
  передают `budget_enforced=True`; экспериментальные env-политики выставляются
  в самих тестах и снимаются после. То есть «feature off» = искусственные
  лимиты не применяются — это и проверяется.
* Заводское состояние SourceReader при любом предикате: `limit_*=0` (потолков
  нет). Положительные лимиты возможны только при ON + явно заданной env-политике.
* Ошибка резолва: `budget_gate` отдаёт fail-open `True`, но искусственных
  потолков всё равно нет (заводского значения не осталось).

### 7.1. Проверка реальным предикатом (без моков)

Проба вне pytest на детерминированном локальном checkout (реальные байты файлов):

```
predicate(real budget_gate) = True          # резолв через существующий API
env policy unset: 0 0 0                     # max_files/depth/requests
no-policy: ok files=10 limits={files:0, depth:0, requests:0, budgets_enforced:True}
env=2:     ok files=2  limits={files:2, depth:0, requests:0, ...} reason=budget
```

То есть: ON без явной политики не включает заводских 6/2/16; явная политика
оператора (`SOURCE_READ_MAX_FILES=2`) честно применяется и видна в
`not_checked.applied_limits`. OFF (см. §3) не применяет её вовсе.

## 8. Оставшиеся швы (следующие слайсы, НЕ C1)

1. `_MAX_REF_CANDIDATES=4`, `_MAX_CANDIDATES=3`, `_MAX_LOCATOR_PATHS=3` (`:170-182`)
   — это C2/`SXR-C2-01`, отдельная запись; в C1 не трогались.
2. Потолки evidence-транспорта: `budget_chars` по-прежнему приходит из
   `tool_router._evidence_window("code")`; OFF-семантика секционных бюджетов —
   слайс C3/evidence transport (композер/сериализатор). SourceReader лишь
   использует полученное окно и не вводит своего.
3. `tool_router._read_source_code` не передаёт `chat_id` в `reader.run()` ⇒
   сейчас действует глобальный слой предиката; per-chat override начнёт
   действовать после одной строки проводки в router (вне C1).
4. `config/settings.py:1484-1498`: комментарии про «3, потолок 6 / 1, потолок 2 /
   8» и сами заводские значения теперь вводят в заблуждение (SourceReader их
   игнорирует). Правка вне C1 (общий файл настроек).
5. Локальный oversized-текст теперь читается диапазонами (см. §0), но каждая
   порция делает один последовательный проход по файлу для точного
   `file_total_lines`/остатка (память постоянна). Для исходников это дёшево;
   если на реальном checkout с очень большими логами стоимость окажется
   заметной — отдельная оптимизация, не смена контракта.
6. GitHub-провайдер по-прежнему упирается в transport-лимит на удалённый
   oversized-файл (Range-запросов `SafeFetcher` не делает) — это категория 2,
   локальный production-путь (LocalSnapshot) покрыт.
7. Поиск `symbol` внутри oversized-файла ограничен доставленной порцией:
   если символа в ней нет, `not_checked.reason="symbol_not_in_page"` и модель
   продолжает диапазонами; полнофайлового поиска символа в oversized-файле нет.
8. `tool_router.py:3691` (путь reuse) пишет `not_checked.depth_left = 0`, тогда
   как свежее чтение отдаёт `None` — косметическая несогласованность вне C1
   (BACKLOG_ONLY).

## 9. Что НЕ проверено (честно)

* Реальный production effective config и реальные ответы GitHub/LocalSnapshot
  не проверялись (нет деплоя). Проверены код-пути на детерминированных
  провайдерах с реальными байтами файлов.
* Сквозной путь «tool-loop → ToolResult → композер → сериализатор → payload
  модели» для >6 файлов принадлежит слайсу B/C3: C1 доказывает, что SourceReader
  отдаёт данные и continuation, а не что каждый следующий слой их не срежет.
* Локальный checkout в тестах — синтетический репозиторий с рукописным `.git`;
  поведение на реальном большом checkout (права, размеры, дерево) не проверялось.

## 10. Housekeeping

Расходники проверок закрыты (`run-close`) для прошлого кандидата; каталог
`temp-206a9ce1b3` (патч/сообщения) закрывается после сдачи. Worktree
сохраняется до ревью (нужен Reviewer/интеграции).
