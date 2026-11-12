# D4-A — binding evidence (contract v1.1, Amendment 1)

**Слайс:** `self-diag-01` / D4-A (только collector identity).
**Контракт:** `plans/features/self-diag-01/architecture-d4-identity.md` §1–§3, §5, §6 и
`## Amendment 1` (contract v1.1, `ARCH_AMENDMENT_READY`), блокеры B1/B2/B3.
**База:** `2587616759de31283585ffc105c91e7193c2e89e` (`release/2.58.197`, `APP_VERSION=2.58.197`).
**Ветка:** `self-diag/d4a` (worktree вне канонического репозитория, `WorkspaceData`).
**Код-коммит:** `8c0359085c5e6419dd27ac7e5c3dc3b8cb98cdf7`
(`fix(self-diag): D4-A amendment 1 - path rule, closed sets, optional manifest schema`).
**Docs-коммит:** этот файл; SHA фиксируется в handoff (коммит не может содержать собственный SHA).
**Supersedes:** code `673fa0e6`, docs `393064d8` (Needs Fixes по B1/B2/B3); старый binding
переименован в этот файл, история сохранена Git.

Артефакты кода (sha256 на код-коммите `8c035908`):

| Файл | строк | sha256 |
|---|---|---|
| `services/deploy_identity.py` | 1162 | `1e394ea9db9e75626a10b2bc14ff3322737640bf96296a56b556a25618e99f22` |
| `tests/test_deploy_identity.py` | 842 | `ef308a8542a6631f4cfdbc3083578f1abe829e54bbc49f6d28555a72447600a1` |

## 1. B1 — path rule (contract v1.1)

`path_is_denied` приведён к точному правилу Amendment 1:

- нормализация `\`→`/`, split по `/`, отброс пустых и `.`; `..`, абсолютный путь,
  буква диска, NUL, пустая/нестроковая строка → `True`;
- для каждого компонента `c = part.strip().lower()`, для точных имён
  `ct = c.rstrip(". ")`;
- deny при любом компоненте: `== ".git"`; содержит `credential`/`secret`/`cookie`
  (без `token`); входит в `{backups, logs, migrate_history, chrome-profile,
  bot-chrome-profile}`;
- basename (`ct`): `.env`, `.env.*` кроме ровно `.env.example`, `*.pem`, `*.key`,
  `*.p12`, `id_rsa*`, `id_ed25519*`, `*.db`, `*.db-wal`, `*.db-shm`,
  `pre_migration_*.db`, `local_database.db`, `*.log`, `deploy_commands.txt`,
  `deploy_result.json`, `check_remote_bot.py`;
- `deploy_*.py` — на любой глубине; единственное исключение — точный полный путь
  `services/deploy_identity.py` (self-read). Варианты регистра, подкаталоги и
  trailing-dot алиасы не исключаются.

`realpath`/symlink/outside-repo проверки остались отдельными (`_read_text_inside`,
`_resolve_git_dir`, `_read_manifest`) и не заменены лексическим предикатом.

Независимые кейсы Reviewer на новом кандидате:

| Путь | Результат |
|---|---|
| `config/credentials/notes.txt` | `True` |
| `config/secrets/notes.txt` | `True` |
| `media/cookies/notes.txt` | `True` |
| `services/deploy_evil.py` | `True` |
| `services/deploy_identity.py` | `False` (self-read) |
| `Services/deploy_identity.py` | `True` |
| `services/sub/deploy_identity.py` | `True` |
| `services/deploy_identity.py.` | `True` |
| `services/tokenizer.py`, `tokenizer.py` | `False` (`token` не запрещён) |

## 2. B2 — закрытые наборы schema 1

`CODES` (5): `verified_deployed`, `local_unverified`, `mismatch`, `unknown`,
`unavailable`.

`REASONS` (23, ровно contract v1.1):

```
no_manifest, manifest_invalid_json, manifest_incomplete, manifest_sha_invalid,
no_git, gitdir_unavailable, head_unresolved, dirty_unknown, dirty_tracked,
git_unavailable, git_timeout, sha_conflict, version_conflict,
process_predates_deploy, no_remote_ref, root_missing, root_not_dir,
permission_denied, path_denied, no_process_start, version_unknown,
internal_error, ""
```

Смысл трёх причин Amendment 1 и `dirty_tracked`:

- `no_process_start` → `local_unverified`: `process_started_at` не передан/не
  разобран; D6-потребитель — `deploy_identity.reason` в блоке identity,
  снимает бейдж «подтверждено».
- `version_unknown` → `local_unverified`: манифест валиден, runtime
  `APP_VERSION` недоступен; D6 не имеет права печатать «версия совпадает».
- `internal_error` → `unavailable`: только непредвиденное исключение верхнего
  уровня `collect_identity`/`recent_commits`; не общая свалка известных ветвей.
- `dirty_tracked` → `local_unverified`: наблюдаемое `dirty=true`; D6-потребитель
  — `reason` и предупреждение «рабочее дерево изменено после релиза».
  `dirty_unknown` остался только для «не удалось определить» (`dirty is None`).

Top-level ключи записи (19; `conflict_values` — только при `code="mismatch"`):

```
schema, code, reason, repo_origin, deployed_sha, checkout_sha, dirty,
upstream_head, version_provenance, local_source_verification, artifact,
deployed_at, observed_at, sources, conflict, local_identity, effect,
previous_sha, previous_version
```

Вложенные закрытые наборы:

- `upstream_head = {sha, ref, observed_at, reason}`; `reason` — `""` или
  `no_remote_ref`;
- `version_provenance = {runtime, manifest, consistent}`;
- `artifact = {kind, release_branch, schema_version}`;
- `local_identity = {checkout_sha, dirty, checkout_mtime, branch}`
  (дубль `upstream_ref` удалён);
- `effect`/`previous_sha`/`previous_version` — блок «релиз/откат», только из
  манифеста, `null` без манифеста; `effect` принимает только `deploy`/`rollback`;
- `conflict_values = {source_name: value}` добавляется только при `mismatch`
  (env-конфликт: оба 40-hex SHA), иначе ключа нет.

Тесты: `test_closed_sets_and_record_keys_match_contract_v1_1`,
`test_unavailable_runtime_version_is_local_unverified`,
`test_unexpected_top_level_exception_is_internal_error`,
`test_missing_process_start_is_local_unverified`,
`test_dirty_tracked_tree_is_never_verified`,
`test_manifest_dirty_tracked_blocks_verified`,
`test_manifest_env_conflict_keeps_both_values`.

## 3. B3 — `schema` опционален

`_read_manifest`: `schema` отсутствует → schema 1; присутствует и `!= 1` →
`unknown/manifest_incomplete`; unknown keys по-прежнему отвергаются. Обязательны
только `deployed_sha`, `deployed_at`, `version`, `effect`.

- B3-a: `test_manifest_without_schema_is_schema_1_and_verifies` — манифест ровно
  из четырёх полей, HEAD/sha/version/process сходятся → `verified_deployed`,
  `reason=""`, `sources` содержит `release_manifest`.
- B3-b: `test_manifest_schema_2_is_unknown` — тот же манифест с `schema: 2` →
  `unknown/manifest_incomplete`.
- `test_manifest_effect_must_be_deploy_or_rollback` — закрытые значения effect.
- `test_manifest_unknown_key_is_rejected` — закрытый набор ключей сохранён.

## 4. Тесты и точные результаты

- `pytest tests/test_deploy_identity.py -q` → **38 passed**.
- `pytest tests/test_deploy_identity.py tests/test_checkup_service.py
  tests/test_checkup_prompts.py tests/test_checkup_handlers.py
  tests/test_checkup_logs_fetcher.py -q` → **149 passed**.
- Полный suite не запускался (аддитивный модуль, изменение только двух файлов).

14 сценариев контракта §5.2 сохранены и проходят; к ним добавлены B1/B2/B3
тесты. Ключевые имена:

| Блок | Тесты |
|---|---|
| 14 сценариев | `test_no_manifest_is_...`, `test_manifest_sha_differs_...`, `test_dirty_tracked_tree_is_never_verified`, `test_no_git_directory_is_unknown`, `test_broken_manifest_json_...`, `test_gitdir_file_outside_repo_is_rejected`, `test_dot_git_symlink_outside_repo_is_rejected`, `test_path_is_denied_contract_set`, `test_repository_code_is_never_imported_or_executed`, `test_verified_deployed_requires_...`, `test_process_started_before_deploy_is_not_verified`, `test_missing_or_file_repo_root_is_unavailable`, `test_recent_commits_clamps_limit_...`, `test_manifest_version_conflict_with_runtime`, `test_env_fallback_without_manifest` |
| B1 | `test_path_is_denied_components_and_deploy_any_depth` + расширенный `test_path_is_denied_contract_set` |
| B2 | `test_closed_sets_and_record_keys_match_contract_v1_1`, `test_unavailable_runtime_version_is_local_unverified`, `test_unexpected_top_level_exception_is_internal_error`, `test_manifest_dirty_tracked_blocks_verified` |
| B3 | `test_manifest_without_schema_is_schema_1_and_verifies`, `test_manifest_schema_2_is_unknown`, `test_manifest_effect_must_be_deploy_or_rollback` |
| Прочее | env-конфликт, env без `.git`, invalid `deployed_at` (4), missing fields (4), unreadable manifest, invalid SHA, unknown key, no process start, утечки |

## 5. RED и mutation на точном кандидате

- **B1 RED:** старый модуль из `673fa0e6` + финальные тесты:
  `pytest tests/test_deploy_identity.py -k "path_is_denied" -q` →
  **2 failed, 34 deselected** (`test_path_is_denied_contract_set`,
  `test_path_is_denied_components_and_deploy_any_depth`). На новом коде те же
  тесты проходят.
- **B3-a RED:** старый модуль +
  `pytest ... -k "manifest_without_schema" -q` → **1 failed, 35 deselected**
  (`unknown` вместо `verified_deployed`). На новом коде проходит.
- **Dirty mutation:** в новом модуле строка `elif dirty is True:` временно
  заменена на `elif False and dirty is True:`; `pytest ... -k
  "dirty_tracked_tree" -q` → **1 failed** (`verified_deployed` вместо
  `local_unverified`). После восстановления — **1 passed**.
- Мутации/старый код не закоммичены; восстановленный модуль имеет sha256
  `1e394ea9...`; worktree чист от кодовых изменений после коммита.

## 6. Что закрывает D4-A, что остаётся

D4-A даёт кандидатное доказательство для строк, проверяемых чистой функцией и
тестами (contract §7.2): `SD1-D4-05`, `SD1-D4-06`, `SD1-D4-08`, `SD1-D4-12`
(часть «не исполнять код»), `SD1-D2-25` (после B1), `SD1-D2-29a` (часть «нет
секретов в записи/ссылках»), `SD1-D4-07` — частично (семантика
`local_unverified`). Статусы карты Builder не меняет; D4/self-diag не
объявляются DONE — решение Reviewer.

Остаётся:

- **D4-B:** `LocalSnapshotProvider` и маршрутизация `SourceReader`,
  `repo_origin` как админ-настройка с событием смены (`SD1-D4-01/03/04/13`,
  `SD1-SEM-04`, `SD1-AC-17`, полный `SD1-D4-07`).
- **D6:** вызов `collect_identity(repo_root, process_started_at=status.started_at)`
  и `recent_commits` на explicit чекап, секция user-контента, корреляция
  traceback, бюджет/лог `[checkup] identity`, аутентифицированный UI
  (`/api/status`), `SD1-D2-29b`; `prompts.checkup_system_prompt` не меняется.
- **D4-C/D7 и live:** `SD1-D4-09/10/14`, `SD1-AC-03/06/17` — реальный чекап/деплой.
- **DevOps `EXT-DEPLOY-MANIFEST`:** запись `.deploy/release.json` по §1.2–§1.3.
  До неё прод честно `local_unverified` (допустимо по `SD1-D4-08`).

## 7. Честные границы и конфигурация

1. **Прод-манифеста ещё нет.** В production `.deploy/release.json` не создан;
   D4-A в проде без манифеста покажет `local_unverified`. `verified_deployed`
   включится сам после первого штатного deploy-прогона DevOps. Live-deploy в
   этом слайсе не выполнялся.
2. **`process_started_at` — шов.** Функция не импортирует `status_service`;
   D6 обязан передать `status.started_at`. Без параметра `verified_deployed`
   невозможен (`local_unverified/no_process_start`) — покрыто тестом.
3. **`recent_commits`** реализован как API §5.1, кламп 1..5 и базис покрыты;
   exact-vs-ancestor semantics `deployed=true` должен подтвердить D6. Реальный
   бюджет «≤3 git-вызова на чекап» и лог `[checkup] identity` — D6, здесь не
   live-проверены.
4. **`git log` timeout** маппится в `git_unavailable`, не `git_timeout` —
   известный minor из ревью, не входил в B1/B2/B3; кандидат его не расширяет.
5. **Linked git worktree:** `.git` — файл с `gitdir:` вне корня; по контракту
   §5.1 это `unknown/path_denied|gitdir_unavailable`, покрыто тестом 6.
   Production — обычный checkout `/var/www/admin_bot`; identity-пробу на корне
   linked worktree запускать нельзя.
6. **Read-only:** модуль сам не пишет; `git status` вызывается с
   `GIT_OPTIONAL_LOCKS=0`, тест 3 проверяет побайтовую неизменность
   `.git/index`. Probe подтвердил `index_unchanged=True`.
7. **Конфигурация:** флагов/провайдеров D4-A не добавляет. Acceptance-critical:
   отсутствие `.deploy/release.json` (production) и `process_started_at=None`
   (D4-A) дают честный `local_unverified`; `ADMINBOT_DEPLOYED_SHA` не задан в
   тестовой среде, кроме тестов с `monkeypatch`. После D6 effective-конфигурация
   `status.started_at` должна реально передаваться.
8. **UI/визуальных изменений нет** — D6 владеет отображением; Playwright/
   Browser Use для D4-A неприменимы.

## 8. Findings

- **BACKLOG / D4-B:** `.gitignore:7` (`deploy_*.py`) матчит
  `services/deploy_identity.py` на любой глубине. Amendment 1 прямо
  классифицирует это как packaging risk, не блокер D4-A и не часть контракта;
  файл остаётся tracked (force-add в `673fa0e6`, изменения в `8c035908`
  отслеживаются). Минимальное действие при следующей правке deploy-контракта:
  `/deploy_*.py` или `!services/deploy_identity.py`.
- **CRITICAL_OUT_OF_SCOPE:** нет.
- **IN_SCOPE:** новых блокеров нет; B1/B2/B3 закрыты этим кандидатом и
  проверяются Reviewer повторно.

## 9. Состав кандидата

Диф против `25876167`: три новых файла — `services/deploy_identity.py`
(1162 строки), `tests/test_deploy_identity.py` (842 строки), этот binding (238
строк). Исходный коммит `673fa0e6` + исправляющий `8c035908`; docs-коммит
содержит переименованный/обновлённый binding. Прод, `master`, `settings`,
prompts, models, `handlers/checkup.py`, `checkup_service.py`,
`source_reader.py`, `capability_registry.py`, `web/*`, `.gitignore`, БД и
хранилища не изменялись. Деплой не выполнялся.
