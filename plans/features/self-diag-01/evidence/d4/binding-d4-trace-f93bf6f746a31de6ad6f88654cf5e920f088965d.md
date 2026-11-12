# D4-C — binding evidence: traceback ↔ deployed SHA (`SD1-D4-10`, `SD1-D4-14`)

**Слайс:** `self-diag-01` / D4-C (финальные строки D4, переданы в D6-трейн).
**Контракт:** `plans/owner_inputs/2026-11-09-self-diag-01.md` строки 131 и 334;
`architecture-d4-identity.md` §4.2 («Корреляция traceback с deployed SHA»).
**База:** `16fa04e77c56db44c23cb5c8a9386f6cfd756628` (`self-diag/d6`).
**Ветка:** `self-diag/d4-trace` (worktree вне канонического репозитория, `WorkspaceData`).
**Код-коммит:** `f93bf6f746a31de6ad6f88654cf5e920f088965d`.
**Docs-коммит:** этот файл; его SHA фиксируется в handoff (коммит не содержит собственный SHA).

Артефакты кода (sha256 на код-коммите):

| Файл | sha256 |
|---|---|
| `services/deploy_identity.py` | `87e79f6f3b697f78979b69fb8f06ec356de5ef3dd6e584774df7745e28f5f627` |
| `services/runtime_probes.py` | `04d7b15156f4c1be2b047293a603f0923cd5f481d45732f69912ad79c7d10a2c` |
| `services/diagnostic_collector.py` | `21c1ebf2b1c10cacdf1a7093b76280eac01d1db292ae0292350384090f85fdba` |
| `services/evidence_bundle.py` | `14f3e39eae36be504593cade3fb89824303fa28f5b81c24495140cdfa497db1e` |
| `tests/test_deploy_identity_d4c.py` | `87850e19675eed3d7b909a64cc826748f01c1c17481d2f63d8952a73d296dfa7` |

## 1. Что реализовано

Новый публичный API (schema 1) в существующем D4-модуле identity:

```python
CORRELATION_SCHEMA = 1
CORRELATION_AXES = ("event_time", "release_install", "changed_files",
                    "changed_symbols", "call_chain", "commit_diff")
CORRELATION_STATUSES / CORRELATION_VERIFICATIONS / CORRELATION_BASES /
CORRELATION_VERDICTS / CORRELATION_REASONS   # закрытые наборы

correlate_traceback(repo_root=None, *, traceback_text, event_at=None,
                    event_source="log_ring", max_files=3, max_commits=3,
                    budget_chars=3000, identity=None) -> dict
```

Запись отвечает на обе строки контракта:

* **время события** (`event.at/source/parsed`) и **установка релиза**
  (`release.deployed_sha/deployed_at/previous_sha/checkout_sha/upstream_sha/
  verification/basis`), плюс `event.relation` =
  `event_after_release | event_before_release | unknown`;
* **call chain** (`call_chain[]`: depth, repo-relative `file`, `function`,
  `line`, `in_repo`, `answering`, `caller`; для кадров вне репозитория — только
  `external_name`, без абсолютных путей хоста);
* **отвечающий файл/функция/caller** (`answering`: file/function/line,
  `exact_frame`, `caller_file/caller_function/caller_line`);
* **изменённые файлы/символы** (`files[]` для отвечающего файла и кадров
  call chain; `changed_symbols` из тела diff и из hunk-контекста git,
  `symbol_match` = пересечение с функциями call chain);
* **commit diff** (`commit_diff`: sha, path, added/removed, symbols,
  hunk_headers, bounded lines, `truncated`, `lines_truncated`).

Ключевые инварианты:

1. Изменения считаются **внутри релиза**: диапазон `previous_sha..deployed_sha`
   (basis `release_diff`); при отсутствии `previous_sha` — только коммиты,
   достижимые из `deployed_sha` (basis `recent_before_release`, честный
   `degraded/no_previous_sha`).
2. Коммиты вне `deployed_sha` (`deployed..HEAD` и `deployed..upstream_ref`)
   помечаются `deployed=false`, попадают ТОЛЬКО в `excluded` с
   `reason="undeployed_commit"` и не могут стать `candidates`.
3. `blame.newest_commit` заполняется (сначала неразвёрнутый кандидат, иначе
   HEAD/upstream), но `newest_blamed=false` и
   `newest_reason="recency_is_not_evidence"` — новизна не доказательство.
4. `event_before_release` → вердикт `event_precedes_release`; изменения релиза
   переносятся в `excluded` с причиной `event_precedes_release` и в
   `candidates` не попадают.
5. Нет `deployed_sha`/git/кадров/отвечающего файла — честные
   `unknown|degraded|unavailable` + `not_checked` по осям, без исключений
   (`correlate_traceback` никогда не бросает: верхний `except` →
   `unavailable/internal_error`).

Безопасность и границы:

* только чтение: `git status` (существующий identity), `git log --name-only`,
  `git show`; фиксированный argv, `shell=False`, таймаут на вызов ≤3 c,
  суммарный дедлайн корреляции 3 c, `budget_exhausted` в `not_checked`-стиле;
* pathspec: только repo-relative `.py/.pyi` внутри `repo_root` после
  `resolve()`; запрещены абсолютные пути вне корня, `..`, ведущий `-`,
  `:`/`*`/`?`/`[`/`]`/`!`/`\`/NUL, denylist `path_is_denied`; `--` отделяет
  ревизии от путей; ревизии — только валидные 40-hex SHA;
* текст (subjects, diff lines, имена функций) проходит **существующий**
  sanitizer `log_ring.sanitize` через `evidence_bundle.sanitize_text` —
  второй копии правил нет; сам traceback-текст наружу не отдаётся, только
  структура;
* никакой сети/GitHub, записи, кэша, DDL, нового стора или LLM.

Переиспользование существующего D3/D4 (без второй ветки данных):

* `evidence_bundle.traceback_frames` — публичная форма существующего
  `_parse_traceback` (тот же разбор, что `stack_summary`);
* `evidence_bundle.sanitize_text` — публичная форма существующего sanitizer'а;
* `collect_identity` / манифест `.deploy/release.json` / `_read_head` /
  `_read_upstream` / `_run_git` / `path_is_denied`.

## 2. Интеграция в существующий путь

* **Probe** `deploy.traceback` (area `deploy`, `READ_SCOPE_REPO`, без
  аргументов) в существующем реестре `runtime_probes`:
  берёт последний traceback из существующего in-process error ring
  (`logs.errors`-источник), identity — через существующий
  `identity_collector` + `status.started_at`, корреляция — в `asyncio.to_thread`
  с внутренним дедлайном меньше probe-timeout. Нет traceback →
  `status=ok`/`reason_code=no_error_traceback` + все оси в `not_checked`
  (это не «здоров»); ring недоступен → `unavailable/log_ring_unavailable`;
  внутренний таймаут → `degraded/correlation_timeout` (внешний probe-timeout
  не маскирует причину).
* **Bundle/tool facts**: наблюдение отдаётся как существующий источник
  `deploy:traceback` (owner `repo`) с плоскими скалярами
  (`answering_file/answering_function/caller_function/blame_verdict/
  deployed_sha/release_installed_at/release_verified/release_basis/
  newest_commit/newest_commit_blamed/deployed_candidates/excluded_undeployed/
  truncated`) плюс полная структура `facts.correlation`; `source_ref` =
  `store=external, entity_type=unknown, entity_id=commit:<deployed_sha>,
  resolution=unknown` (git-коммит — не хранимая сущность проекта, поэтому
  entity_type честно `unknown`, а не выдуманный новый тип).
* **Explicit чекап**: `deploy.traceback` добавлен в существующий список
  проверок `DiagnosticCollector.collect_for_checkup` — те же факты попадают
  в facts-блок чекапа (`answering_file=...`, `blame_verdict=...`,
  `newest_commit_blamed=False`) и в tool-путь `inspect_runtime`.
* **Инцидентный сценарий** `incidents.investigate_incident` (шаг 4 ТЗ §11)
  получил `deploy.traceback` в children — сценарий «после обновления перестал
  обрабатывать голосовые» теперь включает сверку с deployed SHA.
* `bundle.code_lookup_attempted` теперь выставляется из факта: `True` только
  если найден отвечающий repo-файл (раньше всегда `False`).
* `handlers/checkup.py`, `checkup_service.py`, системный промпт, `web/*`,
  `config/settings.py`, БД, `.gitignore` **не менялись**.

Измерение бюджета (реальная фикстура, `max_output_chars=9000`):
сериализованная страница tool-результата с полной корреляцией — **6880
символов**, `facts_omitted` отсутствует; фактический размер зависит от длины
call chain/diff (капы: 10 кадров, 3 файла, 12 коммитов, 16 строк diff).

## 3. RED → GREEN

RED снят на базе `16fa04e7` (тот же файл тестов, код сервисов возвращён к базе
через `git stash`; восстановление — `git stash pop`):

```
$ pytest tests/test_deploy_identity_d4c.py -q      # на 16fa04e7
E  AttributeError: module 'services.deploy_identity' has no attribute 'correlate_traceback'
E  AttributeError: module 'services.evidence_bundle' has no attribute 'traceback_frames'
E  assert 'request:unknown_probe' == 'deploy:traceback'   # probe не зарегистрирован
19 failed in 12.90s
```

GREEN на `f93bf6f7`:

```
$ pytest tests/test_deploy_identity_d4c.py -q      # 20 passed in 16.46s
```

## 4. Тесты (20, герметичные tmp-repo, без сети и прода)

| # | Тест | Что наблюдается |
|---|---|---|
| 1 | `test_deployed_change_is_candidate_and_undeployed_is_excluded` | `verified_deployed` + basis `release_diff`: кандидат — только deployed-коммит; неразвёрнутый `C` в `excluded` (`deployed=false`), `newest_commit=C`, `newest_blamed=false` |
| 2 | `test_checkout_at_deployed_sha_is_verified_ok` | HEAD=deployed: `ok`, `excluded=[]`, newest=deployed, не обвинён |
| 3 | `test_missing_manifest_is_unknown_and_not_comparable` | без манифеста: `unknown/no_deployed_sha`, `not_comparable`, кандидатов нет, `changed_files/commit_diff` в `not_checked`, answering-файл всё равно найден |
| 4 | `test_call_chain_reports_answering_file_function_and_caller` | порядок кадров, `in_repo/external_name`, answering `services/voice.py:handle_voice`, caller `services/router.py:route`; абсолютные пути хоста не утекают |
| 5 | `test_inner_external_frame_keeps_repo_answering_frame` | внешний внутренний кадр: `exact_frame=false`, answering остаётся repo-файлом, caller — предыдущий кадр |
| 6 | `test_commit_diff_is_scoped_to_release_and_answering_file` | diff только deployed-коммита и отвечающего файла; `handle_voice` в symbols; строки `+/-`; неразвёрнутый текст не попадает; `symbol_match=true`; файл call chain без коммитов |
| 7 | `test_diff_budget_truncates_without_breaking_result` | 60-строчное изменение при `budget_chars=400`: `truncated=true`, статус `degraded/budget_exhausted`, added посчитан полностью, показ ограничен |
| 8 | `test_no_secret_leak_and_no_shell_injection` | Bearer-секрет из diff/traceback не утекает; пути `...; touch pwned`, `/etc/shadow`, `backups/*.py` отклонены; каждый argv — `git`, `shell=False`, инъекционных строк в argv нет |
| 9 | `test_git_timeout_is_graceful` | `git log/show` таймаут → `degraded/git_timeout`, `not_comparable`, кандидатов нет, answering сохранён |
| 10 | `test_missing_git_and_root_and_frames_are_honest` | нет `.git` → `unknown/no_git`; нет root → `unavailable/root_missing`; нет кадров → `unknown/no_frames`; пустой traceback → `ok/no_traceback` + оси в `not_checked`; только внешние кадры → `degraded/no_answering_file` |
| 11 | `test_event_before_release_does_not_blame_release_change` | событие раньше релиза: `event_precedes_release`, релизное изменение не в `candidates` |
| 12 | `test_probe_exposes_correlation_in_tool_facts` | probe-источник `deploy:traceback`, `status=ok`, `source_ref=commit:<deployed>`, плоские факты + полная структура, `newest_commit_blamed=false`, `excluded_undeployed>=1`, `bundle.code_lookup_attempted=true`, `runtime_sha=deployed` |
| 13 | `test_probe_without_error_traceback_is_not_checked` | нет ERROR-traceback: `ok/no_error_traceback`, все 6 осей в `not_checked`, `correlation=null`, `code_lookup_attempted=false` |
| 14 | `test_probe_log_ring_unavailable_is_honest` | ring бросает → `unavailable/log_ring_unavailable`, без исключения |
| 15 | `test_probe_timeout_degrades_without_raising` | зависшая корреляция → `degraded/correlation_timeout` (внутренний дедлайн раньше probe-timeout), оси в `not_checked` |
| 16 | `test_checkup_path_includes_traceback_correlation` | explicit-чекап: источники `deploy:traceback` + `deploy:identity`; в facts-тексте `answering_file`, `blame_verdict`, `newest_commit_blamed=False`; `code_lookup_attempted=true` |
| 17 | `test_closed_sets_and_never_raises` | закрытые наборы статусов/базисов/вердиктов; мусорные входы (`None`, `object()`, identity без SHA) → валидная запись, не исключение |
| 18 | `test_result_is_json_serialisable` | все ключевые поля присутствуют, `schema=1`, JSON-сериализуемость |
| 19 | `test_public_traceback_frames_helper` | публичный разбор кадров/exception, пустой текст → пустой список |
| 20 | `test_incident_scenario_includes_traceback_correlation` | сценарий инцидента содержит `deploy.traceback`; probe зарегистрирован, `READ_SCOPE_REPO`, `configured=true`, без аргументов |

## 5. Focused-прогоны (только затронутые файлы; полный suite не запускался)

```
pytest tests/test_deploy_identity_d4c.py -q
  → 20 passed

pytest tests/test_deploy_identity.py tests/test_deploy_identity_d4b.py
       tests/test_evidence_bundle.py tests/test_diagnostic_probes.py
       tests/test_checkup_contract.py tests/test_checkup_service.py
       tests/test_checkup_handlers.py tests/test_p0_checkup_core_contract.py
       tests/test_diagnostic_policy.py -q
  → 366 passed, 1 warning
```

Итого **386 passed** на `f93bf6f7`; D4-A/D4-B/D3/D6-контракты не
регрессировали. Прод, деплой, реальные чаты и настройки не затрагивались.

## 6. Честные границы

1. **Preprod, без live.** Проверки — только unit/integration на temp-repo и
   probe/collector-шве; реальный `/var/www/admin_bot` и фактический
   `.deploy/release.json` не проверялись (манифеста в проде до первого
   штатного deploy-прогона может не быть — тогда честно `unknown/
   no_deployed_sha`). `live_required=false` по карте, live-when `preprod`.
2. **Только локальный checkout.** Сверка идёт с локальными refs: `HEAD` и
   `refs/remotes/origin/<branch>`. Сеть/GitHub не используется, поэтому
   «неразвёрнутый коммит, существующий только на origin и не подтянутый
   локально» не виден — это честный `not_checked`, а не «коммитов нет».
3. **Только Python-кадры** (`.py/.pyi`). Кадры библиотек/бинарных вызовов
   помечаются `in_repo=false` (`external_name`), их изменения не
   коррелируются.
4. **Каппы и обрезка видимы**: 10 кадров, 3 файла, 12 коммитов, 16 строк diff,
   6 hunk-заголовков, 3 c на все git-вызовы корреляции. Превышение caps →
   `truncated=true` (или `lines_truncated` только для показа) и `degraded/
   budget_exhausted`; молчаливой потери нет.
5. **Sanitizer паттерновый**, а не «поиск любого секрета в коде»: известные
   env-секреты, Bearer/prefix/URI-креды маскируются (проверено тестом), но
   произвольная секретоподобная строка в чужом исходнике не доказуемо
   распознаётся. Сам traceback-текст в запись не включается.
6. **Одна запись на последний traceback.** Корреляция берёт последний
   ERROR-кадр из ring (≤5 записей, первый с `exc_text`); исторические
   traceback'и в одном ответе не перебираются.
7. **`answering` может быть не внутренним кадром**: если исключение возникло
   в библиотеке, отвечающим считается ближайший repo-кадр, а
   `exact_frame=false` честно это показывает.
8. **`source_ref` с `entity_type=unknown`**: git-коммит не является хранимой
   сущностью проекта (в `provenance.STORES/ENTITY_TYPES` нет commit-типа),
   поэтому тип не выдуман; адрес — `external/commit:<sha>`.
9. **UI/визуальных изменений нет** — Playwright/Browser Use неприменимы;
   витрина D6 не менялась.
10. **Флаги не добавлялись.** Поведение зависит от существующих источников:
    `.deploy/release.json` (deployed_sha/previous_sha/deployed_at/version),
    локальных refs git, `status.started_at`, in-process error ring и
    `SELF_DIAG_LOCAL_REPO_ROOT`/cwd для repo root. Тесты используют только
    temp-репозитории; production-значения не переопределялись.

## 7. Границы коммита

Диф против `16fa04e7`: 5 файлов, +1642/−12 — `services/deploy_identity.py`
(+715), `services/runtime_probes.py` (+155), `services/diagnostic_collector.py`
(+22/−12), `services/evidence_bundle.py` (+23),
`tests/test_deploy_identity_d4c.py` (новый, 739 строк). Прод, настройки,
промпты, БД/DDL, `handlers/checkup.py`, `checkup_service.py`, `web/*`,
`.gitignore`, новые зависимости и второй стор не появлялись. Деплой не
выполнялся.

## 8. Замечания для Reviewer

* D4-10/D4-14 закрываются **кандидатным** доказательством (unit + probe/
  collector-шов). Независимая проверка и решение по статусам строк — за
  Reviewer/PM; Builder статусы в карте не менял и approval не заявляет.
* Спорное место, требующее независимой проверки: `degraded` при
  `deployed_unverified` — релизные изменения показываются, но
  `release.verification=not_confirmed` прямо говорит, что сверка с
  исполняемой ревизией не подтверждена; обвинение не формируется.
* Второе спорное место: добавление `deploy.traceback` в explicit-чекап и
  инцидентный сценарий увеличивает число источников на 1 (бюджет страницы
  измерен: 6880/9000 на фикстуре). Если Reviewer считает это расширением
  D6-контракта — откат локальный (одна строка в `collect_for_checkup` и одна
  в children сценария).
