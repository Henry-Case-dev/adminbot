# SMART-CORRECTIVE-01 — S1-CONTRACT + S2-SOURCEREADER implementation evidence

Статус: **REVIEW** (кандидат для независимого ревью; не VERIFIED).
Дата: 2026-11-14.

## Идентичность кандидата

- Epic: `smart-corrective-01`, срезы `S1-CONTRACT` + `S2-SOURCEREADER`.
- Базовая линия: `release/2.58.200` @ `13884daa32e5cf2a1c05c5c43188ca299f8179f8`
  (код = deployed `0e4a144db476a1535ae3a2b79a7cce30354ad866` + release docs).
- Рабочая ветка: `sc/corrective-s1s2`.
- Code candidate commit (production state): `f007da3314685a86346739db5329a904a5d48093`
  (implementation `86872aac` + диагностическое удаление candidate-sample cap).
- Test-only additions + эта evidence-запись: коммиты после code candidate в той же ветке
  (final branch HEAD сообщается Orchestrator; расхождение — только tests/evidence,
  production-код остаётся `f007da33`).
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-90a1abda`
  (managed `WorkspaceData/worktrees`, registered как `s1s2-source`).

## Изменённые файлы (production)

`services/source_reader.py` — единственный production-файл. Изменения:

1. **Структурированный результат/статусы.** Добавлен канонический `outcome`
   (`ok`, `ambiguous`, `not_found`, `search_failed`, `partial`,
   `source_unavailable`, `permission_denied`, `provider_limit`,
   `revision_mismatch`, `unsupported`) при сохранении прежнего `status` для
   существующих потребителей. Добавлены `partial`, `query`, `operation`,
   `progress_id`, `idempotency_key`, `continuation`, `matches`, `match_count`,
   `ranked_materials`, `content_search`, `candidate_paths_total`.
2. **Provenance/source selection.** `provenance` дополнен `repo`, `commit`,
   `operation`, `outcome`, `progress_id`; `source_selection` — `requested_ref`,
   `requested_commit`, `checkout_sha`, `deployed_sha`, `identity`,
   `selection_reason`. При remote-fallback `checkout_sha` пуст (не выдаётся за
   удалённую идентичность).
3. **Поиск по содержимому.** `_MAX_LOCATOR_PATHS = 3` и `ranked[:3]` удалены.
   `_content_search()` проверяет реальные байты всех доступных текстовых файлов
   доступной ревизии; порядок структурный: implementation → caller → tests →
   migration → deploy_script → documentation → plans → other; внутри класса
   используется существующий `rank_paths()` как подсказка (не потолок).
   Поддержаны exact strings, dotted identifiers (`watchdog.jobs`), имена
   символов, event/process id, config keys, traceback-фрагменты (через
   кавычки/dotted/identifier-пробы), imports/calls; `context_query` добавляет
   литералы. Никаких таблиц «известная команда → известный файл» нет.
4. **Порционная выдача/продолжение.** `partial` + opaque cursor
   (`base64` JSON + sha256-префикс) с identity `repo/commit/query/symbol/provider`,
   `scan_index`, `resume_path`, `resume_line`; повторный вызов продолжает с
   места остановки, не повторяет выданные вхождения. Для строк файла —
   `continuation.kind="file_lines"` и `next_arguments.line_start`; для follow-up —
   `kind="followup"` и `untried_paths`. `progress_id` стабилен между страницами.
5. **Fallback.** Ровно один local→remote по точному deployed commit при:
   недоступном/усечённом локальном дереве, техническом отказе локального
   маршрута, неверифицированном snapshot без найденной реализации, локальной
   ревизии, которую локальный источник не может отдать (только если это
   запрошенный deployed SHA). Явно запрошенная *другая* 40-hex ревизия не
   подменяется deployed SHA → `revision_mismatch`. Повторного
   remote→local/локального цикла нет: `_maybe_switch_to_remote()` срабатывает
   только из local и только один раз. `permission_denied`/path-denied никогда не
   обходятся удалённым чтением; denylist путей применяется и к содержимому
   поиска.
6. **Точная ревизия/лимиты провайдера.** GitHub для 40-hex commit закреплён на
   этом commit (без подстановки default branch); ветка разрешается один раз в
   commit и читается pin-но. Rate-limit/timeout → `provider_limit`,
   auth/path-denied → `permission_denied`, технический отказ/недоступность
   источника → `source_unavailable`, нечитаемый поиск после bounded retry
   (1 повтор на временный отказ) → `search_failed`. Физический бюджет скана
   (`content_scan_budget_bytes()`, default 8 MiB/вызов, env
   `SOURCE_READ_CONTENT_SCAN_BYTES`) не является semantic top-N: исчерпание
   даёт `partial` + cursor, а не ложное `not_found`.
7. **Честные причины.** `oversized`/`missing`/`unreadable`/`not_text`/
   `denied` учитываются в `content_search.skipped`; непрочитанная часть дерева
   не позволяет вернуть `not_found` — только `partial` с причиной.

## Изменённые тесты

- `tests/test_smart_corrective_source_reader.py` (new, 25 tests): content search
  не по имени файла и за пределами top-3, реализация/caller/tests/docs/plans/
  migration/deploy, exact `watchdog.jobs`, `not_found`, `partial` + cursor
  (включая продолжение без повтора), `search_failed`, `source_unavailable`,
  `permission_denied`, `provider_limit`, `revision_mismatch`, fallback
  local→remote exact commit, недоступное/усечённое дерево, отсутствие
  подмены явно запрошенной чужой ревизии, remote-cursor на том же провайдере,
  отсутствие сетевого обхода denied-пути, provenance/source_selection/
  progress/idempotency, совместимость `tool_result.classify_output` с
  `partial`/`not_found`.
- `tests/test_evol_source_reader.py::test_payload_never_carries_chat_chronology_or_quotes`:
  прежнее точное равенство набора ключей `provenance` ослаблено до «обязательные
  технические ключи присутствуют, chat-хронология/цитаты отсутствуют». Это
  изменение контракта (новые обязательные provenance-поля), а не сокрытие
  дефекта; старый инвариант «никакой chat-хронологии» сохранён.
- Иные существующие тесты не ослаблялись. `test_evol_source_reader.py`,
  `test_smart_e_local_first_source.py`, `test_smart_c1_source_reader_limits.py`
  проходят без изменения поведения старого контракта.

## Команды и фактические результаты (worktree, offline/test fixtures)

```
py -3 -m pytest tests/test_evol_source_reader.py \
  tests/test_smart_e_local_first_source.py \
  tests/test_smart_c1_source_reader_limits.py \
  tests/test_smart_corrective_source_reader.py -q
=> 157 passed, 2 warnings

py -3 -m pytest tests/test_tool_router.py \
  tests/test_mca11_tool_result_round1028.py \
  tests/test_tool_loop.py tests/test_checkup_service.py \
  tests/test_checkup_contract.py tests/test_selfdiag_corrective_research.py \
  tests/test_smart_exec_selfdiag.py tests/test_smart_exec_evidence.py \
  tests/test_diagnostic_policy.py -q
=> 310 passed, 3 warnings

py -3 -m py_compile services/source_reader.py
=> OK
```

Предупреждения pytest — известный `Unknown config option: timeout` (плагин
timeout не установлен); на результат не влияет.

### Реальное локальное дерево (read-only probe, no network)

Artifacts:
`plans/features/smart-corrective-01/evidence/s1s2/real-tree-search.json`
(sha256 `71C5B42297C0E1E1F8C177BC4A229F364FB6B06460FA87492B7FF1BFB8F165AB`) и
`.../real-tree-continuation.json`
(sha256 `7D808E03C04A3BAD8FC842121938B67BA621732BF5B46DA362BC32BD2194EF31`).

Наблюдаемые результаты:

- `query="watchdog.jobs"` → `status=ok`, `outcome=partial`,
  `path=services/mca_watchdog.py`, `match_line=154`,
  `match_material=implementation`, `match_count=1`,
  `probes=["watchdog.jobs"]`, `files_scanned=163`,
  `network_calls=0`, provider `local_snapshot`. Это тот же реальный файл и
  реальная строка (`process_id="watchdog.jobs"`), не harness-скрипт и не
  первый попавшийся файл.
- Generic non-watchdog `query="incident_opened"` → `path=services/mca_incidents.py`,
  `match_material=implementation`, `probes=["incident_opened"]`,
  `network_calls=0`.
- Продолжение по cursor на реальном дереве: страница 1 — implementation
  (`services/mca_watchdog.py`), страницы 2 — implementation/mention, страницы 5–6
  — tests, страницы 9–10 — plans; `progress_id` одинаковый на всех страницах,
  курсор продолжает без повтора выданных файлов. Дерево в teстовом worktree
  дало `running_unverified` и revision `files-2.58.200` (это локальный
  unverified snapshot, не production checkout); поэтому probe доказывает
  маршрут/классы, а commit-bound `verified=true` доказывается synthetic SHA-bound
  тестами.

## Покрытие acceptance rows

### S2-SOURCEREADER (31 required row)

| Row | Покрытие/доказательство |
|---|---|
| SC-SRC-PRIO-01 | LocalSnapshotProvider выбран первым; `test_verified_local_tree...`, `test_identifier_not_a_filename...`, existing `test_verified_local_code_is_read_without_network`; real-tree probe provider=local_snapshot, network_calls=0. |
| SC-SRC-PRIO-02 | Существующий `resolve_local_source` (configured/runtime identity) не заменён вторым локальным SourceReader; `tests/test_smart_e_local_first_source.py` (root discovery/identity/limits) проходит; identity/verification поля в `source_selection`. |
| SC-SRC-PRIO-03 | GitHub только по exact commit: `test_unverified_local_search_uses_exact_deployed_commit_once`, `test_exact_commit_mismatch_is_revision_mismatch`; remote stub invoked at SHA; default branch не подставляется. |
| SC-SRC-FB-01 | `test_local_tree_unavailable_search_falls_back_once`; discover/commit fallback при недоступном local root. |
| SC-SRC-FB-02 | `test_truncated_local_tree_search_falls_back_to_exact_commit`; listing None → `source_unavailable`/fallback. |
| SC-SRC-FB-03 | Fallback при `version_verified=False` (`test_unverified_local_search...`); verified local absence stays `not_found` без сети (`test_verified_local_absence...`). |
| SC-SRC-FB-04 | `test_unverified_local_search...` + existing `test_unverified_snapshot_missing_file_may_use_exact_deployed_commit` (файл есть в deployed revision, локально отсутствует). |
| SC-SRC-FB-05 | `test_retryable_read_error_bounded_retry_then_source_unavailable` + fallback local read_error existing `test_local_read_error_falls_back_to_exact_deployed_commit`. |
| SC-SRC-FB-06 | `test_unverified_local_search...` (осмысленный локальный поиск без implementation → remote exact); verified local complete scan не делает лишнего network. |
| SC-SRC-CLASS-01 | `test_verified_local_absence_is_honest_not_found_without_network` (outcome `not_found`). |
| SC-SRC-CLASS-02 | `test_search_failure_after_bounded_retry_is_search_failed` (outcome `search_failed`, code parse_error; bounded retry test для retryable-ошибки). |
| SC-SRC-CLASS-03 | `test_scan_budget_returns_partial_and_cursor_continues`, `test_scan_budget_without_hit_is_honest_partial_not_not_found`, line continuation test (outcome `partial` + cause). |
| SC-SRC-CLASS-04 | `test_tree_unavailable_is_source_unavailable` (outcome `source_unavailable`, reason tree_unavailable). |
| SC-SRC-CLASS-05 | `test_permission_denied_is_not_bypassed_by_remote` (outcome `permission_denied`, `path_denied`, no fallback). |
| SC-SRC-CLASS-06 | `test_provider_rate_limit_is_provider_limit` (outcome `provider_limit`). |
| SC-SEARCH-FIND-01 | Investigation/architecture fix confirms deployed `_MAX_LOCATOR_PATHS=3`; current code removes it; durable `test_fixed_locator_cap_is_gone` asserts attribute absent. |
| SC-SEARCH-FIND-02 | Deployed `ranked[:_MAX_LOCATOR_PATHS]` removed; content scan covers all searchable entries (`test_identifier_not_a_filename_found_beyond_top_three`, files_scanned>3; real-tree page1 163 files). |
| SC-SEARCH-FIND-03 | Deployed `rank_paths()` path/name signal confirmed; now it is only a scan-order hint, not qualification: content bytes decide (`test_content_search...`, `_content_search`). |
| SC-SEARCH-CAP-01 | exact strings: `test_identifier_not_a_filename...` (`ledger.reconcile.marker` exact in bytes). |
| SC-SEARCH-CAP-02 | symbols: `test_symbol_query_distinguishes_implementation_and_callers`; `test_repo_name_then_locate_then_verified_read` (existing). |
| SC-SEARCH-CAP-03 | event/process ids: real-tree `watchdog.jobs`, `incident_opened`; synthetic content tests. |
| SC-SEARCH-CAP-04 | config keys: `_search_probes` dotted/raw identifiers; `_looks_like_definition` key forms; tests use dotted marker/key. |
| SC-SEARCH-CAP-05 | traceback fragments: quoted/dotted/identifier probes and line-level matching; synthetic query coverage; limitation noted below (multi-line block not a single substring). |
| SC-SEARCH-CAP-06 | imports/calls: caller classification test (`from ... import`, `reconcile()`); `_code_role_for_line`. |
| SC-SEARCH-CAP-07 | context refinement: `context_query` adds literals; `rank_paths` uses query/symbol/path/language; `_content_search` qualifies by bytes; real-tree generic query. |
| SC-SEARCH-KIND-01 | implementation: real-tree mca_watchdog/mca_incidents, synthetic payments_worker; `MATERIAL_IMPLEMENTATION`. |
| SC-SEARCH-KIND-02 | caller: `test_symbol_query_distinguishes_implementation_and_callers` (`payments_caller.py`). |
| SC-SEARCH-KIND-03 | documentation: synthetic `docs/payments.md` material `MATERIAL_DOCUMENTATION`; tests/plans classes also returned (`GENERIC_FILES`, real-tree pages). |
| SC-SEARCH-KIND-04 | migration: synthetic `migrations/0007_ledger.sql` material `MATERIAL_MIGRATION`. |
| SC-SEARCH-KIND-05 | deploy script: synthetic `scripts/deploy_payments.sh` material `MATERIAL_DEPLOY_SCRIPT` (denylist `deploy_*.py` не читается — security). |
| SC-SEARCH-KIND-06 | mentions without implementation: synthetic/real-tree `MATERIAL_MENTION`; plans (`MATERIAL_PLANS`) и tests (`MATERIAL_TESTS`) различаются отдельно. |

### S1-CONTRACT (26 rows)

S1-CONTRACT rows map to planning/process contracts, already fixed before
implementation (requirements-map, `architecture-plan.md`, `slice-graph.json`,
source register/overlap checks). This candidate implements the code-facing
SourceReader contract part of S1; it does **not** create a new epic, second
engine, vector index or repo DB.

- `SC-COR-IDENT`, `SC-COR-GOAL`, `SC-COR-PARENT`, `SC-COR-REGISTER`,
  `SC-COR-STAGES`, `SC-COR-REJ-01..06`: satisfied by corrective registration
  (`plans/features/smart-corrective-01/`), frozen architecture contract and the
  fact that this candidate changes only the existing SourceReader contour; no
  reports/status rewriting, no prompt-only fix, no tool-existence-only tests,
  no feature shutdown, no owner-live substitution.
- `SC-OVL-SOURCES`, `SC-OVL-MAP-01..05`, `SC-OVL-EPICS`: PM/Architect baseline
  artifacts (requirements map / architecture plan / slice graph) exist and were
  consumed; this Builder lane did not modify owner-owned planning files.
- `SC-COR-NOTVERIFIED`, `SC-COR-DELIVERY`, `SC-ART-NOTDONE`: status remains
  REVIEW; production/deployed evidence and final acceptance are not claimed
  here.

## Ограничения и явно непроверенное

1. **ToolRouter forwarding (S3 scope).** `services/tool_router.py` не входит в
   write scope S2 и не изменялся: он по-прежнему не передаёт `chat_id`/
   `budget_enforced`/`cursor` в `SourceReader.run()`. Cursor и effective policy
   готовы на уровне SourceReader, но доступны только прямым/вложенным
   потребителям, которые их передают. Это остаётся S3-BUDGET / downstream
   integration gap; в production-инструменте `read_source_code` продолжение
   поиска потребует передачи cursor в следующем срезе.
2. **Reuse payload.** `source_reuse` в ToolRouter возвращает прежнюю форму без
   `outcome`/`progress_id`/`idempotency_key`; свежие чтения SourceReader несут
   новый контракт. Это consumer в S3/S4, вне write scope S2.
3. **Production effective config.** Production-доступ не использовался.
   `SOURCE_READ_ENABLED` (default ON), `SOURCE_READ_MAX_FILE_BYTES` (2 MiB),
   `SOURCE_READ_CONTENT_SCAN_BYTES` (default 8 MiB) проверены на тестовом
   окружении; фактический production precedence и deployed SHA должен
   подтвердить DevOps/Reviewer на release-эталоне. Новых флагов/shadow-режимов
   нет; поведение активно при первом деплое.
4. **Локальный worktree unverified.** В worktree `resolve_local_source` дал
   `running_unverified`/`files-2.58.200`; commit-bound `verified=true`
   доказывается synthetic SHA-bound тестами, но не реальным production
   checkout. Это честная граница: real-tree probe доказывает маршрут/классы/
   отсутствие сети, а не production-подтверждение байтов.
5. **Поиск per-line.** Точные вхождения ищутся по строкам; многострочный
   traceback-блок целиком не является одной подстрокой. Классы
   `search_failed`/`partial` для непрочитанных/слишком больших файлов
   сохраняют честную причину (`oversized`/`missing`/`unreadable`).
6. **Pre-existing release-line drift.** `tests/test_tool_coordinator_round1026.py`
   даёт 2 падения (`TOOL_CALLING_TOOLS` 18 vs 17; allowlist web-diff), не
   связанные с этим кандидатом: изменены только `source_reader.py` и два
   SourceReader-теста, `tool_schemas.py`/`web/` не тронуты. Классификация:
   `BACKLOG_ONLY` (устаревшие ожидания release-линии), не блокер S1/S2.
7. **SC-SEARCH-FIND-01..03** — это investigation-факты *deployed* кода; в
   текущем кандидате они подтверждены удалением старого пути, а не сохранением
   константы. Evidence фиксирует это различие.

## Housekeeping

- Probe run: `WorkspaceData/runs/.../probe-6f825565c9` (owned unit
  `s1s2-source`), результаты промотированы в durable evidence JSON выше;
  закрывается `run-close` после ревью (если Reviewer/DevOps ещё не нужен живой
  worktree, закрыть вместе с unit).
- Worktree остаётся зарегистрированным до завершения review; удаление/закрытие
  — после join и переноса доказательств.
