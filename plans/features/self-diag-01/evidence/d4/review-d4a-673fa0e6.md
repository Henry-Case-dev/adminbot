# D4-A - независимое ревью deployed identity

Дата: 2026-11-12. Reviewer, не Builder и не автор evidence.
Кандидат: code 673fa0e67481119108dcae7c511f835fd3271d69, docs 393064d8a0d55cae50ab17a7a8c16f9a497bd46c.
База: 2587616759de31283585ffc105c91e7193c2e89e (2.58.197).
Ветка/worktree: self-diag/d4a, ...-8dd6c752.

**Вердикт: Needs Fixes.** D4-A не принят: path denylist уже контракта (security),
закрытые reason/field наборы расширены без contract amendment, manifest schema
требуется, хотя контракт называет его опциональным. D4/self-diag DONE не
объявляются; карта и progress_scope не менялись.

## 1. Состав кандидата

- Diff 25876167..HEAD: 3 новых файла - services/deploy_identity.py (1145),
  tests/test_deploy_identity.py (642), evidence binding (191).
- Существующие модули, .gitignore, settings, prompts, handlers/checkup,
  checkup_service, source_reader, capability_registry, web/* не менялись.
- services/deploy_identity.py и tests/test_deploy_identity.py tracked
  (git ls-files, cat-file HEAD:...); commit 673fa0e6 добавляет их как A.
- .gitignore:7 = deploy_*.py матчит services/deploy_identity.py; файл
  force-added и tracked. Это packaging risk, не runtime blocker (см. section 6).

## 2. Implementation audit

- Приоритет: manifest .deploy/release.json -> .git HEAD/ref/packed-refs ->
  env ADMINBOT_DEPLOYED_SHA только при no_manifest. Валидный manifest не
  перебивается env; env+manifest conflict даёт mismatch/sha_conflict.
- verified_deployed требует manifest + sha==checkout + dirty=false +
  version==runtime APP_VERSION + process_started_at >= deployed_at.
  Процесс раньше deploy -> mismatch/process_predates_deploy; нет process
  start -> local_unverified/no_process_start.
- Нет manifest -> local_unverified/no_manifest (env не поднимает выше);
  manifest != HEAD -> mismatch/sha_conflict с обоими SHA;
  нет .git -> unknown/no_git; битый JSON -> unknown/manifest_invalid_json;
  недоступный root -> unavailable/root_missing|root_not_dir;
  never-raise обёртка есть.
- Безопасность: git вызывается фиксированным argv, shell=False, timeout 3 c,
  env минимальный + GIT_OPTIONAL_LOCKS=0; нет fetch/pull/ls-remote;
  .git/config/HEAD/refs/packed-refs читаются только внутри root; symlink
  или gitdir вне root -> path_denied/gitdir_unavailable; repo_origin
  нормализуется до owner/name, userinfo/токены вырезаются; абсолютные
  host paths и .env в record не попадают; код репозитория не импортируется
  и не исполняется; кэша/БД/записи нет.
- Проверены поля и коды; расхождения с закрытым контрактом - section 4.


## 3. Тесты и mutation

- pytest tests/test_deploy_identity.py -q -> **31 passed** на кандидате.
- Combined: tests/test_deploy_identity.py + test_checkup_service.py +
  test_checkup_prompts.py + test_checkup_handlers.py +
  test_checkup_logs_fetcher.py -> **142 passed**.
- Прочитаны assertions: 14 сценариев контракта, dirty, no manifest,
  mismatch, no .git, broken JSON, symlink/gitdir, denylist, no exec,
  verified conditions, process before deploy, root missing, recent_commits
  clamp/basis, version conflict, env fallback, env conflict, dirty_tracked,
  no process start, no secrets/host paths. Тесты не тавтологичны для этих
  сценариев; fake repo и real git используются по делу.
- Пробелы тестов: test_path_is_denied_contract_set проверяет basenames
  (secret.txt, cookies.txt), но не пути с каталогами credentials/secrets/
  cookies; нет теста manifest без schema; нет теста закрытого набора
  reason/field (тесты наоборот закрепляют расширения).

**Mutation (на точном кандидате 393064d8, disposable worktree):**

- В services/deploy_identity.py строка dirty-check заменена на
  `elif False and dirty is True:`;
- запуск tests/test_deploy_identity.py -> **1 failed, 30 passed**,
  FAILED test_dirty_tracked_tree_is_never_verified (line 179);
- restore `git checkout -- services/deploy_identity.py`; повторный запуск ->
  **31 passed**, git status чистый; worktree удалён.

## 4. Независимые контрпримеры

**C1. Denylist не ловит каталоги credentials/secrets/cookies:**

`python -c` на кандидате:

- `path_is_denied("config/credentials/notes.txt")` -> **False**
- `path_is_denied("config/secrets/notes.txt")` -> **False**
- `path_is_denied("media/cookies/notes.txt")` -> **False**
- `path_is_denied("services/deploy_evil.py")` -> **False**
- `path_is_denied("secret.txt")` -> True (basename-only check)

Контракт §3.3: `*credentials*`, `*secret*`, `*cookies*` и `deploy_*.py`
должны запрещаться; фактический `.gitignore` матчит их на любой глубине.
Код проверяет только `name` (последний компонент) и deploy_*.py только в
корне. Это false negative: файл `config/credentials/prod.txt` с безопасным
именем будет разрешён будущему file reader (SD1-D2-25).

**C2. Manifest без schema отклоняется:**

Temp repo: `.git/HEAD`, `.deploy/release.json` с обязательными полями
`deployed_sha`, `deployed_at`, `version`, `effect`, но без `schema`.
`collect_identity` -> **unknown/manifest_incomplete**. Контракт §1.2:
`deployed_sha, deployed_at, version, effect` обязательны, остальные
опциональны; schema не входит в обязательные. Код требует `schema == 1`
(line 330), то есть отвергает contract-valid manifest.

**C3. Закрытые reason/field наборы расширены:**

- `set(di.REASONS)` минус контракт §2.3 -> **no_process_start,
  version_unknown, internal_error**;
- `collect_identity(None)` keys минус контракт §2.2 -> **effect,
  previous_sha, previous_version**;
- `upstream_head` extra key **reason**; `local_identity` extra key
  **upstream_ref**; при env conflict добавляется **conflict_values**.

Контракт называет schema 1 закрытой. Тесты закрепляют расширения
(no_process_start, upstream_ref, env conflict_values), а не контракт;
это contract deviation, а не additive-only без последствий.


## 5. Блокеры

### B1 (security, Builder): path denylist уже контракта

Требование: contract section 3.3, SD1-D2-25; predicate должен запрещать
`*credentials*`, `*secret*`, `*cookies*`, `deploy_*.py` на любой глубине.
Факт: C1 выше; `config/credentials/notes.txt`, `config/secrets/notes.txt`,
`media/cookies/notes.txt`, `services/deploy_evil.py` -> False.
Минимальный fix: проверять все компоненты `lower`, а не только `name`;
для deploy_*.py сделать точное исключение только для
`services/deploy_identity.py` (или contract amendment, если root-only
задумано). Добавить negative tests на directory components. Затрагивает
SD1-D2-25 и будущий D4-B; без fix D4-A не принят.

### B2 (contract, Architect + Builder): закрытые reason/field наборы

Требование: schema 1 closed, contract section 2.2/2.3. Факт C3:
`REASONS` extra no_process_start/version_unknown/internal_error; record
extra effect/previous_sha/previous_version; upstream_head.reason;
local_identity.upstream_ref; conflict_values. Тесты закрепляют расширения.
Минимальный fix: либо Architect amendment (добавить эти коды/поля и
D6-потребителя в контракт, обновить tests/evidence), либо убрать extras
и использовать только contract set. Без решения D4-05/06/08/29a не закрывать.

### B3 (contract, Builder): manifest без schema отвергается

Требование: contract section 1.2 говорит, что обязательны только deployed_sha,
deployed_at, version, effect; schema не входит. Факт C2: temp repo с этими
четырьмя полями без schema -> unknown/manifest_incomplete (line 330).
Минимальный fix: принимать отсутствие schema как schema 1 или явно
изменить контракт и тест; добавить contract test. Затрагивает D4-05/08.


## 6. Packaging risk .gitignore

- Файл tracked: `git ls-files` и `cat-file HEAD:` подтверждают;
  commit 673fa0e6 добавляет `services/deploy_identity.py` как A.
- Текущий release path - `git checkout`/restart; tracked-файл присутствует.
  `git clean -X`/ignore-respecting packaging может считать его игнорируемым,
  если файл станет untracked; сейчас это не release blocker.
- Классификация: BACKLOG / D4-B + DevOps, не блокер D4-A. Минимальное
  действие при следующей правке deploy-контракта: `deploy_*.py` ->
  `/deploy_*.py` или добавить `!services/deploy_identity.py`; в D4-A
  .gitignore по контракту не меняется.

## 7. Строки D4-A

- Сейчас ни одну строку D4-A не следует помечать VERIFIED: B1 держит
  SD1-D2-25; B2/B3 держат D4-05 (valid manifest/closed set); D4-08
  no-manifest path passes, но row-level closure waits for B2 contract decision.
- После B1/B2/B3 поведенчески поддержаны и могут закрываться:
  SD1-D4-05 (после contract fix), SD1-D4-06 (HEAD не выдаётся за deployed,
  test 2), SD1-D4-08 (no manifest -> local_unverified, contract fix),
  SD1-D4-12 (код не исполняется), SD1-D2-29a subset (record без секретов).
- SD1-D4-07 - только частично: local_unverified semantics есть; полный
  local snapshot provider/маршрутизация - D4-B.
- SD1-D2-25 - только после B1; сейчас FAILED/не закрывать.
- Остаётся D4-B: SD1-D4-01/03/04/13, SD1-SEM-04, SD1-AC-17, полный D4-07
  (SourceReader/LocalSnapshotProvider, repo_origin admin setting).
- D6: SD1-D4-09/10/14, SD1-D2-29b, UI/trace, user-content section, лог
  `[checkup] identity`; D4-A не пишет handlers/checkup.py/checkup_service.py.
- D4-C/D7/live: SD1-AC-03/06/17, live checks D4-09/10/14; production
  `.deploy/release.json` - DevOps EXT-DEPLOY-MANIFEST.
- Production limit: без manifest D4-A в проде честно `local_unverified`;
  `verified_deployed` возможен только после DevOps manifest и D6
  `process_started_at=status.started_at`. Это допустимо по D4-08, не DONE.


## 8. Три опоры

- Implementation: прочитаны contract sections 1-6, services/deploy_identity.py
  (1145 строк), tests/test_deploy_identity.py (642), evidence binding;
  проверены priority, five verified conditions, never-raise, git argv/env,
  symlink/gitdir, repo_origin, recent_commits. Diff 3 new files confirmed.
- Test validity: 31/142 passed; assertions прочитаны; mutation dirty
  check дала 1 failed/30 passed, restore -> 31 passed. Тесты сильны для
  covered scenarios, но зелёные при C1/C2/C3; поэтому 31/142 не доказывают
  полный контракт.
- Independent challenge: C1 denylist directory false; C2 manifest без
  schema unknown/manifest_incomplete; C3 extra reasons/fields; mutation
  dirty check red. Всё наблюдалось на точном кандидате.

## 9. Остаточные ограничения

- `recent_commits` помечает deployed=true только точный deployed SHA;
  ancestors получают false. Contract говорит о false для недостижимых;
  D6 должен подтвердить exact-vs-ancestor semantics. Не блокер D4-A,
  но зафиксировать в D6.
- `git log` timeout маппится в git_unavailable, не git_timeout; minor.
- Linked worktree `.git` gitdir вне root -> path_denied; production
  обычный checkout, но identity-пробу нельзя запускать на linked worktree.
- Live/UI/container not run; D4-A pure function; Playwright/Browser Use
  неприменимы; production manifest отсутствует -> local_unverified.
- Никаких изменений кода/настроек/прода Reviewer не делал; mutation
  worktree удалён, provided worktree чист; карта/progress_scope не менялись.

