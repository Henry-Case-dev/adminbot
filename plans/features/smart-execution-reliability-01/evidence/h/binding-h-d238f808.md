# S8-SELFDIAG (этап H) — binding evidence

- **Epic:** SMART-EXECUTION-RELIABILITY-01, срез **S8-SELFDIAG** (этап H).
- **Owner input:** `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md`, §H1-§H5.
- **Требования:** `SXR-H1-01`, `SXR-H1-02`, `SXR-H2-01`, `SXR-H3-01`, `SXR-H4-01`, `SXR-H5-01`.
- **База интеграции:** ветка `smart/h-selfdiag` от E (`18fa4d59`) + merge S3
  (`5e87ed48`, коммит `6baca863`) + merge G (`cffc9fb2`, коммит `ce9e9f01`).
- **CODE_SHA:** `d238f808` (коммит H-кода и тестов; evidence-файлы идут
  отдельным docs-коммитом).
- **Изменённые файлы:** `services/checkup_prompts.py`,
  `services/system_logs_fetcher.py`, `services/diagnostic_collector.py`,
  `handlers/checkup.py`, новый `tests/test_smart_exec_selfdiag.py`,
  `plans/features/smart-execution-reliability-01/evidence/h/**`.
- Деплой/прод/миграции/новые флаги не выполнялись. Схема БД не менялась.

## 0. Разрешение merge-конфликта (до H)

Конфликт был ровно один: `services/response_extent.py` (G против S3 fix).
Обе стороны сохранены:

- G: удалены мёртвые `PLAN_MAX_STEPS`/`PLAN_MAX_REPLANS` (план не обрезается
  по числу шагов, re-plan не исполнялся).
- S3 (C2/C3): заводского потолка ссылок нет, `PLAN_MAX_FETCH_STEPS = 0`,
  действует env-политика `DIRECT_TOOL_PLAN_MAX_FETCH_STEPS` и
  `_fetch_steps_policy()`; ceiling `16384` и `search_query[:256]` не
  возвращены.

Merge-коммит `ce9e9f01`. Дополнительно при combined-прогоне найдено
cross-slice расхождение E×S3: S3-тест `test_smart_exec_evidence.py` объявлял
«локального snapshot нет, только stub-провайдер», но E добавил второй корень
(runtime identity), не управляемый `SELF_DIAG_LOCAL_REPO_ROOT`. Фикстура
дополнена точечным `resolve_local_source -> unusable` (коммит `8c5549b7`),
проверки C2/C3 не менялись. Прогон после merge: **100 passed**
(`test_smart_g_finalize_round1114`, `test_smart_exec_evidence`,
`test_mca23_phase2`, `test_smart_exec_ab_round1114`).

## 1. Что уже было выкачено и не переимплементировалось

2.58.199 (`d20a7f73`) уже содержит corrective SELF-DIAG-01: чекап через общий
`chat_with_tools`, `inspect_runtime`/`read_source_code`, типизированное
`diagnostic_research`, продолжение по ledger `output_kind=checkup_report`,
journal env/manifest identity fixes. Поэтому H добавляет только остаток:

| Остаток §H | Где закрыт в H |
|---|---|
| H1: причины, а не метрики; объект выбирает модель | `checkup_prompts.CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM` (новые операционные правила) |
| H2: продолжение на обычном Direct | существующие `mca_bot_outputs`/`bot_replies` + `direct_l1`; H добавляет контрактный тест и mutation-proof, код не дублируется |
| H3: журнал собственного unit, минимальные права | `system_logs_fetcher` уже читает только свой invocation/unit без shell; H добавляет видимость uid/root и явный `last_state` |
| H4: manifest и runtime identity | существующие `tools/release_manifest.py` + `services/deploy_identity.py`; H доказывает roundtrip, restart и использование SourceReader/чекапом |
| H5: unknown вместо нуля | `diagnostic_collector.collect_for_checkup` (errors_state, порядок фактов, сохранение not_checked) |

## 2. Изменения кода

### 2.1. `services/checkup_prompts.py` (SXR-H1-01, H1-02, H5)

`CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM` (подключается только при реальном
tool-цикле; канон `CHECKUP_SYSTEM_PROMPT` байт-в-байт не менялся) дополнен:

- объект и глубину исследования выбирает модель по фактическим данным;
  готовой таблицы «код ошибки -> файл -> инструмент» нет, технический поиск
  по traceback, символам, модулям и исходникам разрешён;
- без проблем, требующих анализа кода, репозиторий целиком не читается;
- в выводах разделяются подтверждённое рабочее состояние, обнаруженный
  дефект, установленная причина, гипотеза, недоступные сведения и
  рекомендуемое исправление; гипотеза не подаётся как причина;
- unknown/unavailable/not_checked не превращаются в ноль; подтверждённый
  ноль допустим только для реально проверенного окна источника; явно
  описаны `errors_state=confirmed_zero|unknown`.

### 2.2. `services/system_logs_fetcher.py` (SXR-H3-01, H5)

- `last_state`, `last_journal_state`, `last_used_fallback` — фактический исход
  уже выполненного `fetch()`, без второго чтения журнала и без кэша логов.
- В `[log-source]` добавлен `uid=<geteuid()>`; при `uid=0` — отдельная
  `[log-source-note]` о недопустимом root-запуске. На non-POSIX uid
  отсутствует.
- Чтение journal не менялось: фиксированный argv, без shell/sudo, только
  `_SYSTEMD_INVOCATION_ID` своего запуска или `--unit` из своего cgroup;
  чужой unit не подставляется. Внутренний ledger остаётся fallback.

### 2.3. `services/diagnostic_collector.py` (SXR-H5-01, H1-02)

`collect_for_checkup` принимает `log_state`/`journal_state` (если не переданы —
читает `last_state`/`last_journal_state` у того же fetcher'а) и формирует
честный факт вместо молчаливого нуля:

| Фактический исход | status | errors_state | reason |
|---|---|---|---|
| journal unreadable / fallback | `degraded` | `unknown` | `journal_unavailable` |
| окно прочитано, проблемные строки есть | `ok` | `observed` | - |
| окно прочитано, строк нет (`empty`/`info_only`) | `ok` | `confirmed_zero` с `zero_basis=journal_window_read_no_error_lines` | `empty_log_window`/`no_error_markers` |
| исход неизвестен | `not_checked` | `unknown` | `log_state_unknown` |

Состояние журнала ставится первым источником в facts-блоке, чтобы бюджет
фактов не вытеснял unknown/zero. Если бюджет всё же отсёк хвост, перед
текстом добавляется `[facts_unknown] not_checked=...` — непроверенное не
исчезает. Новых счётчиков нет.

### 2.4. `handlers/checkup.py` (SXR-H5-01)

Хендлер передаёт collector'у фактический `log_state`/`journal_state` того же
`fetch()` и пишет их в существующую телеметрию `checkup_triggered`
(`log_state`, `journal_state`), без текста логов.

## 3. Обязательные требования

| ID | Наблюдаемое поведение | Статус Builder | Доказательство |
|---|---|---|---|
| `SXR-H1-01` | Чек-ап использует существующие collector/bundle/inspect_runtime/read_source_code/local/tool-loop/policy/identity; модель выбирает объект; таблицы код->файл нет; поиск по traceback/символам/модулям разрешён; репозиторий целиком без нужды не читается | готово к ревью | §4 `TestCheckupRootCauseContract`; RED d20a7f73 |
| `SXR-H1-02` | Отчёт различает состояние/дефект/причину/гипотезу/unknown/исправление; характер и стиль сохранены | готово к ревью | §4 `TestCheckupReportCategories`; байт-пины канона в `test_checkup_prompts` (168 passed) |
| `SXR-H2-01` | Продолжение обычным Direct: отчёт структурно в L1, tool results текущего исследования доходят до модели, слова-маркеры не нужны, не любая реплика — продолжение | готово к ревью | §4 `TestDiagnosticContinuation`; существующие интеграционные continuation-тесты (124 passed); mutation |
| `SXR-H3-01` | Журнал только своего unit/invocation, без sudo/shell; чужой unit не читается; fallback сохранён; видны права процесса | готово к ревью, production-факт postdeploy | §4 `TestJournalEnvironment`; prod recon: `User=adminbot`, `journalctl` от adminbot rc=0, InvocationID совпал |
| `SXR-H4-01` | `.deploy/release.json` создаётся существующим инструментом, привязан к HEAD/APP_VERSION, переживает рестарт, используется SourceReader и чекапом; задним числом не создаётся | готово к ревью, production-факт postdeploy | §4 `TestDeployManifestIdentity`; prod recon: manifest schema 1, `deployed_sha=d20a7f73`, совпадает с HEAD |
| `SXR-H5-01` | Недоступная наблюдаемость -> unknown/not_checked; работающая и без событий -> подтверждённый ноль; новые счётчики не созданы | готово к ревью | §4 `TestUnknownVersusConfirmedZero`; mutation zero |

## 4. Тесты

Новый файл: `tests/test_smart_exec_selfdiag.py` — 25 тестов (CONTRACT):

- `TestCheckupRootCauseContract` (3): read-only набор `{read_source_code,
  inspect_runtime}` из существующих capabilities, серверная self-identity,
  тот же ERROR-текст не выбирает инструмент сам (два разных выбора модели),
  приписка разрешает traceback/символы/модули и запрещает полный обход.
- `TestCheckupReportCategories` (2): все шесть категорий отчёта, канон
  характера не переписан, facts несут status/reason_code/not_checked.
- `TestDiagnosticContinuation` (3): реальный in-memory ledger
  `output_kind=checkup_report` -> `_recent_checkup_report_text` -> L1-контекст
  без слов «код/репозитор/GitHub/чекап»; `preserved_diagnostic_research`
  только при reply-to-bot; семантическая приписка L1.
- `TestJournalEnvironment` (4): свой invocation, отсутствие sudo/shell,
  отказ чужому unit, permission-отказ -> ledger fallback, uid/root-пометка.
- `TestDeployManifestIdentity` (4): реальный git-фикстур + настоящие
  `release_manifest`/`deploy_identity`; манифест привязан к HEAD/версии,
  грязное дерево -> отказ, identity `verified_deployed`, чтение после
  «рестарта» (новый `process_started_at`) без изменения файла, SourceReader
  `verified_running` и `deploy.identity` чекапа с тем же SHA, отсутствие
  манифеста не фабрикует SHA.
- `TestUnknownVersusConfirmedZero` (9): параметризованные
  unknown/observed/confirmed_zero, `not_checked` при неизвестном состоянии,
  Telegram `delivered=None` без ledger и `0` при работающем ledger, STT
  `failed=None`+`not_checked` без голосовых строк, пустое окно журнала —
  не ноль.

Команды и результаты (venv `C:\Code\Python\adminbot\.venv`, `-p no:cacheprovider`):

| Прогон | Результат |
|---|---|
| `pytest tests/test_smart_exec_selfdiag.py -q` | **25 passed** (`pytest-selfdiag.txt`) |
| `pytest tests/test_checkup_contract.py tests/test_checkup_handlers.py tests/test_checkup_logs_fetcher.py tests/test_checkup_prompts.py tests/test_checkup_service.py tests/test_p0_checkup_core_contract.py -q` | **168 passed** (`pytest-checkup.txt`) |
| `pytest tests/test_selfdiag_corrective_research.py tests/test_deploy_identity.py tests/test_deploy_identity_d4b.py -q` | **124 passed** (`pytest-selfdiag-identity.txt`) |
| `pytest tests/test_deploy_identity_d4c.py tests/test_release_manifest.py tests/test_diagnostic_probes.py tests/test_diagnostic_policy.py -q` | **181 passed, 1 warning** (`pytest-identity-probes-policy.txt`; warning — сторонний Starlette/httpx) |
| `pytest tests/test_smart_e_local_first_source.py tests/test_smart_exec_evidence.py tests/test_mca23_phase2.py tests/test_smart_g_finalize_round1114.py tests/test_smart_exec_ab_round1114.py -q` | **129 passed** (`pytest-integration-seams.txt`) |

Итого по затронутым срезам: **627 passed**, 0 failed. Широкий прогон всего
репозитория не выполнялся: изменения локальны для чекапа/журнала/identity.

## 5. RED на базе d20a7f73

Отдельный detached-worktree `HEAD=d20a7f73` (base 2.58.199, до всех срезов),
файл `tests/test_smart_exec_selfdiag.py` скопирован как есть:

```
python -m pytest tests/test_smart_exec_selfdiag.py -q
13 failed, 12 passed
```

`red-base-d20a7f73.txt`. Падения — именно остаток H:

- `TestCheckupRootCauseContract::test_addendum_allows_technical_search_without_whole_repo`;
- `TestCheckupReportCategories::test_addendum_lists_all_categories_and_keeps_canon_bytes`;
- `TestCheckupReportCategories::test_facts_carry_status_not_only_metrics`;
- `TestJournalEnvironment::test_own_invocation_without_sudo_or_shell`,
  `test_permission_failure_keeps_internal_fallback`,
  `test_process_rights_are_visible_and_root_is_flagged`;
- `TestUnknownVersusConfirmedZero::test_checkup_logs_state_is_honest[...]` (5),
  `test_unknown_state_does_not_become_zero`;
- `TestDeployManifestIdentity::test_source_reader_and_checkup_use_the_manifest`.

12 прошедших на базе — уже выкаченные 2.58.199 части (H2 continuation, часть
H4 identity, модель-выбор инструмента): они не переимплементировались, а
закреплены как регрессия.

## 6. Мутации (проверка, что тесты не тавтологичны)

| Мутация | Файл | RED | Восстановление |
|---|---|---|---|
| `_recent_checkup_report_text` всегда `""` (обрыв structural continuation) | `services/direct_chat_service.py` | `test_report_is_structural_context_without_marker_words` — **1 failed** (`mutation-continuation-red.txt`, diff `mutation-continuation.diff`) | `git checkout --`, diff пуст |
| `errors_state` принудительно `confirmed_zero` (unknown -> ноль) | `services/diagnostic_collector.py` | 4 failed (`mutation-zero-red.txt`, diff `mutation-zero.diff`) | `git checkout --`, diff пуст |
| `build_manifest` пишет `deployed_sha = "0"*40` (манифест с неподтверждённым SHA) | `tools/release_manifest.py` | `test_existing_deploy_tool_writes_manifest_bound_to_release` — **1 failed** (`mutation-manifest-red.txt`, diff `mutation-manifest.diff`) | `git checkout --`, diff пуст |

## 7. Whitespace-контроль

```
git diff --check 8c5549b7 HEAD -- services handlers tools tests   -> пусто, exit=0
git diff --check 8c5549b7 HEAD                                    -> пусто, exit=0
```

`whitespace-check.txt`. Все изменённые файлы — LF (0 CRLF). Единственная
правка после первого коммита — удаление лишней пустой строки в конце нового
тест-файла; кодовые строки не менялись (`git diff -w 33a78b3f d238f808 --
tests/test_smart_exec_selfdiag.py` показывает только это удаление).

## 8. Effective configuration

- `flags.checkup_enabled` — заводски ON; `SOURCE_READ_ENABLED` — ON;
  `MCA_BOT_OUTPUT_LEDGER_ENABLED` — ON; `DIRECT_L1_ENABLED` — ON.
- `SELF_DIAG_LOCAL_REPO_ROOT` — заводски `""`, корень берётся из runtime
  identity (E); `ADMINBOT_DEPLOYED_SHA` — не задан, источник — manifest.
- Новых флагов/настроек/промптов-ключей/счётчиков нет.
- Тестовые override: `last_state`/`last_journal_state` через фикстуры,
  `os.geteuid` monkeypatch, `bot_output_ledger.ledger_enabled` monkeypatch,
  `ADMINBOT_DEPLOYED_SHA` удалён в тесте отсутствия манифеста. Прод-значения
  этими тестами не подменяются.

## 9. Остаток: production/postdeploy (честно не проверено)

Реальный деплой в задачу не входил, production не изменялся. После выката
кандидата DevOps/Reviewer выполняют (одним коротким read-only recon по
правилам SSH/fail2ban):

1. **H3/H4 identity:** `systemctl show admin_bot -p User,Group` = `adminbot`
   (не root); `journalctl -u admin_bot` от `adminbot` rc=0 для нового
   `InvocationID`; `.deploy/release.json` создан штатным деплоем,
   `deployed_sha` = deployed HEAD = manifest, `version` = `APP_VERSION`;
   после рестарта `collect_identity` даёт `verified_deployed`, а чекап —
   `journal_state=ok`, `uid!=0`.
2. **H5 live:** при работающем журнале и отсутствии ERROR-строк отчёт
   называет подтверждённый ноль; при недоступном журнале — unknown;
   Telegram `delivered=0` только при включённом ledger, иначе `None`;
   STT без голосовых строк — `not_checked`, не ноль.
3. **H2 live:** продолжение обычным сообщением без слов «код/репозиторий/
   GitHub/чекап» не просит ссылку и не требует повторных данных; одна
   благодарность не запускает исследование.

Это postdeploy-строки, а не блокер кода; симулировать их в unit-тестах
нельзя.

## 10. Housekeeping

- RED-база: worktree `WorkspaceData/worktrees/...-45d7d5f19c3b-788baca3`
  (detached `d20a7f73`), после переноса RED-лога удалён `git worktree remove`;
  регистрация `smart-h-selfdiag-red` закрыта `unit-close`.
- Одноразовый run под `WorkspaceData/runs/` (probe) закрыт `run-close
  --confirmed-idle --confirmed-evidence --apply` после переноса логов в
  `evidence/h/`.
- Кандидатный worktree сохраняется для Reviewer/интеграции; в репозитории
  временных файлов нет.
