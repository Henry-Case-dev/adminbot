# D4-A re-review (Amendment 1) - Approved

Дата: 2026-11-12. Reviewer, не Builder и не автор evidence.
Кандидат: code 8c0359085c5e6419dd27ac7e5c3dc3b8cb98cdf7, docs 7ad8b2f72ba77aeebc4a77c9eab7b20463bcf0a7.
База: 2587616759de31283585ffc105c91e7193c2e89e (2.58.197).
Ветка/worktree: self-diag/d4a, ...-8dd6c752.
Supersedes: review-d4a-673fa0e6.md (Needs Fixes B1/B2/B3).

**Вердикт: Approved для D4-A.** B1/B2/B3 закрыты на contract v1.1;
поведение прежнего D4-A сохранено. D4/self-diag DONE не объявляются.
Карта и progress_scope не менялись. Продуктовый код/настройки/прод не менялись;
деплоя нет.

## 1. Состав кандидата

- Diff 25876167..HEAD: 3 новых файла - services/deploy_identity.py (1162),
  tests/test_deploy_identity.py (842), evidence binding (238).
- Существующие модули, .gitignore, settings, prompts, handlers/checkup,
  checkup_service, source_reader, capability_registry, web/* не менялись.
- services/deploy_identity.py и тесты tracked (git ls-files, cat-file HEAD).
- .gitignore:7 deploy_*.py матчит модуль; файл tracked; packaging risk
  остается BACKLOG/D4-B, не блокер (section 7).

## 2. B1: path rule

Код проверяет все компоненты на любой глубине, `.git`, credential/secret/
cookie substrings, denied dirs, basename rules; deploy_*.py на любой глубине
с единственным точным исключением `services/deploy_identity.py`;
`token` не добавлен; `realpath`/symlink проверки отдельные.

Независимые вызовы на 8c035908:

- `config/credentials/notes.txt` -> True
- `config/secrets/notes.txt` -> True
- `media/cookies/notes.txt` -> True
- `services/deploy_evil.py` -> True
- `services/deploy_identity.py` -> False
- `tokenizer.py` -> False
- `Config/Credentials/notes.txt` -> True
- `services/sub/deploy_identity.py` -> True
- `services/deploy_identity.py.` -> True
- `credentials./notes.txt`, `secret./x`, `cookies./x` -> True
- `.git./config`, `backups./x` -> True
- `token/notes.txt` -> False (token не запрещён)

Кейсы `..`, absolute, drive, empty покрыты code/test; symlink/gitdir
остаются отдельной проверкой `_read_text_inside`/`_resolve_git_dir`.

## 3. B2: closed sets

- `CODES` = 5; `REASONS` = **23** (dirty_tracked, no_process_start,
  version_unknown, internal_error включены; extras соответствуют Amendment 1).
- Top-level record keys = **19**; `local_identity` = 4 (upstream_ref удален);
  `upstream_head` = 4 (reason присутствует); effect/previous_sha/previous_version
  присутствуют; `conflict_values` только при mismatch.
- Direct: normal record keys 19, no conflict_values; dirty=true ->
  local_unverified/dirty_tracked, keys 19, no upstream_ref; env conflict ->
  mismatch/sha_conflict, keys 20, conflict_values с обоими SHA; без manifest
  effect/previous = None.
- `dirty_unknown` остался только для `dirty is None`; dirty=true не даёт его.


## 4. B3: optional manifest schema

- Manifest ровно из четырех полей (deployed_sha, deployed_at, version,
  effect) без schema -> **verified_deployed**, reason "", sources содержит
  release_manifest; direct на 8c035908: B3A verified_deployed, 19 keys.
- Тот же manifest с schema:2 -> **unknown/manifest_incomplete**.
- effect other -> **unknown/manifest_incomplete**; unknown key ->
  **unknown/manifest_incomplete** (закрытый набор сохранен).
- effect принимает только deploy|rollback; schema отсутствует = 1.

## 5. Тесты и mutation

- pytest tests/test_deploy_identity.py -q -> **38 passed**.
- Combined test_deploy_identity + test_checkup_service + test_checkup_prompts
  + test_checkup_handlers + test_checkup_logs_fetcher -> **149 passed**.
- Assertions прочитаны: B1 four review cases + self-read/tokenizer, B2 closed
  sets/keys, dirty_tracked, version_unknown, internal_error, no_process_start,
  B3-a/B3-b/effect/unknown key; старые 14 сценариев сохранены.
- **Mutation (independent):** в disposable worktree @ 7ad8b2f7 из
  `_DENIED_SUBSTRINGS` убран `"credential"`;
  `pytest ... -k path_is_denied_components -q` -> **1 failed, 37 deselected**
  (`test_path_is_denied_components_and_deploy_any_depth`;
  `assert False is True` для config/credentials/notes.txt).
- Restore `git checkout -- services/deploy_identity.py`; полный файл ->
  **38 passed**, worktree чистый; disposable worktree удален.
- Old-code RED подтвержден прежним прямым наблюдением 673fa0e6:
  config/credentials -> False, manifest без schema -> unknown/
  manifest_incomplete; новые тесты на эти значения падают по построению.


## 6. Прежнее поведение D4-A

- Priority manifest -> git HEAD -> env only no_manifest сохранен.
- Five verified conditions сохранены: manifest, sha==checkout, dirty=false,
  version==APP_VERSION, process_started_at >= deployed_at.
- No manifest -> local_unverified; manifest != HEAD -> mismatch с обоими SHA;
  no .git -> unknown/no_git; broken JSON -> unknown/manifest_invalid_json.
- No shell/network/.env/backups; no import/exec repo code; recent_commits
  clamp 1..5; no writes/caching/new store. Combined 149 green; diff only 3
  new files.

## 7. Packaging и minor

- `.gitignore:7` (`deploy_*.py`) матчит `services/deploy_identity.py`; файл
  tracked и присутствует в commit; release path `git checkout` его включает.
  Классификация: **BACKLOG / D4-B + DevOps**, не блокер D4-A. Minimal action
  позже: `/deploy_*.py` или `!services/deploy_identity.py`; в D4-A .gitignore
  по контракту не меняется.
- `git log` timeout маппится в `git_unavailable`, не `git_timeout`;
  **BACKLOG**, не блокер D4-A (contract Amendment 1 его не расширяет).
- `recent_commits` exact-vs-ancestor semantics `deployed=true` - D6 confirm;
  не блокер D4-A.


## 8. Строки D4-A

- D4-A может закрыть: **SD1-D4-05, SD1-D4-06, SD1-D4-08**; **SD1-D4-12**
  часть "код не исполняется" (full GitHub/SafeFetcher clause - D4-B/AC-17);
  **SD1-D2-25** канонический path predicate (не file reader integration);
  **SD1-D2-29a** subset (record/links без секретов).
- **SD1-D4-07** - только частично: local_unverified semantics; полный
  provider/маршрутизация остается D4-B.
- D4-B: SD1-D4-01/03/04/13, SD1-SEM-04, SD1-AC-17, полный D4-07
  (SourceReader/LocalSnapshotProvider, repo_origin admin setting).
- D6: SD1-D4-09/10/14, SD1-D2-29b, UI/trace, user-content section, лог
  `[checkup] identity`; D4-A не пишет handlers/checkup.py/checkup_service.py.
- D4-C/D7/live: SD1-AC-03/06/17, live checks D4-09/10/14; production
  `.deploy/release.json` - DevOps EXT-DEPLOY-MANIFEST.
- D4/self-diag DONE не объявляются.

## 9. Production limit

Без `.deploy/release.json` D4-A в проде честно показывает
`local_unverified`; `verified_deployed` включится после DevOps manifest
и D6 `process_started_at=status.started_at`. Это допустимо по D4-08;
live-деплой D4-A не выполнялся.

## 10. Три опоры

- **Implementation:** прочитаны contract v1.1/Amendment 1, модуль (1162),
  тесты (842), binding; проверены B1 path, B2 sets/keys, B3 schema,
  priority/five conditions/no shell/no exec/recent_commits.
- **Test validity:** 38/149 passed; assertions прочитаны; mutation B1
  removal of credential -> 1 failed/37 deselected; restore -> 38 passed.
  Old-code RED подтвержден prior direct results; не Builder prose.
- **Independent challenge:** B1 cases true/false exact; B2 23 reasons/19 keys/
  19-key record, dirty_tracked, conflict_values only mismatch; B3 verified
  without schema, schema2/effect/unknown key unknown; mutation observed.

## 11. Остаточные ограничения

- `recent_commits` exact-vs-ancestor `deployed` semantics - D6; не блокер.
- `git log` timeout -> git_unavailable - minor/BACKLOG.
- Linked worktree `.git` gitdir вне root -> path_denied; production normal.
- Live/UI/container не запускались; D4-A pure function; production manifest
  отсутствует -> local_unverified.
- .gitignore packaging risk - BACKLOG/D4-B/DevOps; файл tracked.
- Reviewer не менял код/настройки/прод; mutation worktree удален;
  provided worktree содержит только review-файлы; карта/progress_scope
  не менялись.

