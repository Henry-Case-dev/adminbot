# D4-B - независимое ревью local snapshot и repo_origin

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code 722ccfc522ba00a18dc74881913020151ac250aa, docs b6d7064c7dfdb3bbb334f91dfb106b66a60fdd47.
База: approved D4-A 8c0359085c5e6419dd27ac7e5c3dc3b8cb98cdf7; root base 25876167 (2.58.197).
Worktree: self-diag/d4b, ...-63c55c03.

**Вердикт: Approved для D4-B (unit/preprod).** D4/self-diag DONE не
объявляются; D6/D4-C/D7/live остаются. Карта и progress_scope не менялись;
продуктовый код/настройки/прод не менялись; деплоя нет.

## 1. Состав кандидата (фактический)

- Diff **vs D4-A base 8c035908: 65 файлов**, не 3. Ядро: services/source_reader.py
  (+609), services/param_catalog.py, services/tool_router.py,
  config/settings.py, tests/test_deploy_identity_d4b.py,
  tools/_selfdiag01_d4b_reissue_f8.py; остальное - F8/пины.
- Строка brief «Diff vs 25876167: 3 новых файла, source_reader/settings
  unchanged» относится к D4-A, не к D4-B. Vs 25876167 входят D4-A (3 файла)
  и D4-B (65 файлов); source_reader/settings/param_catalog/tool_router
  изменены ожидаемо.
- Не тронуты: handlers/checkup.py, services/checkup_service.py, prompts,
  models, web/*, .gitignore, capability_registry, БД/сторы. Подтверждено diff.
- services/deploy_identity.py и tests/test_deploy_identity.py tracked;
  .gitignore:7 deploy_*.py матчит deploy_identity.py, но source_reader не
  матчит; файл tracked, release path включает (BACKLOG/D4-B, не блокер).

## 2. Implementation audit

**LocalSnapshotProvider:** name local_snapshot; реализует search_repos,
resolve_repo, resolve_commit, list_tree, read_file. Read/list только внутри
repo_root после realpath; path_is_denied на каждом чтении/листинге;
commit-pinned только HEAD; другой SHA -> provider_unavailable/
commit_not_available; bytes -> существующий decode_source_bytes/build_snippet;
file size max SOURCE_READ_MAX_FILE_BYTES; наружу repo-relative path;
identity через D4-A collect_identity (нет второго .git parser);
network_calls=0, uses_auth=False; import/exec/subprocess кода репозитория нет.

**SourceReader routing:** GitHub default; local только exact casefold
owner/name == repo_origin; provider выбран в _RunState на вызов;
self.provider не мутируется; сторонний repo/fork -> GitHub; local payload
помечает provider/local_snapshot, local_source_verification, local_source_note;
clean HEAD+commit -> verified=true с repo:// ссылкой; dirty=true ->
verified=false; local_unverified не выдаётся за deployed.

**repo_origin:** flags.self_diag_repo_origin, non-secret, flags_service,
tab mod_checkup, global_only → per_chat=False; default Henry-Case-dev/adminbot;
normalize owner/name strips scheme/host/userinfo/token; invalid -> default;
hot.get; event repo_identity_changed old/new/by=config; actor остаётся в
существующей строке [api] config updated (partial D4-03); no new page/store.

**tool_router:** _source_pointer больше не hardcode github; provider/host/
local_source_verification/local_source_note сохраняются в reuse; GitHub
defaults github/github.com. **settings:** SELF_DIAG_LOCAL_REPO_ROOT - env-only
ClassVar default "", no dataclass field delta; local provider off by default.


## 3. Security/denylist: наблюдённые результаты

- path_is_denied: config/credentials/notes.txt -> True; media/cookies/notes.txt
  -> True; .git/config -> True; services/deploy_evil.py -> True;
  services/deploy_identity.py -> False; tokenizer.py -> False.
- LocalSnapshotProvider.read_file: credentials/cookies/.git/deploy depth/ADS
  (services/source_reader.py:stream) -> SourceFetchError path_denied;
  services/deploy_identity.py -> success self-read; symlink outside -> path_denied;
  missing root -> provider_unavailable/root_missing.
- Dirty snapshot: payload verified=False, local_source_verification=
  local_unverified; test asserts note «рабочее дерево изменено».
- Exact owner: Henry-Case-dev/ADMINBOT -> local/local_snapshot; other/mod ->
  github/github.com; fork не local.
- repo_origin URL с user:secret@ -> Henry-Case-dev/adminbot; secret не в
  записи/логе; per_chat=False; existing POST chat-scope route rejects 422
  (web/api/routes.py: `if not spec.per_chat`).
- SELF_DIAG_LOCAL_REPO_ROOT default -> ""; local provider off; build_local_
  provider None; SourceReader._local_provider None.
- path_is_denied/realpath: лексический predicate + отдельный realpath;
  symlink/outside проверки не заменены.

## 4. Тесты, RED и mutation

- pytest tests/test_deploy_identity_d4b.py -q -> **58 passed**.
- Focused 610 set из binding evidence -> **610 passed**, 1 warning.
- Два pre-existing RED идентичны на кандидате и базе 8c035908:
  tests/test_cfg03_param_audit.py::TestConsumerCoverage::test_visible_dead_
  knobs_are_exactly_documented и tests/test_tool_coordinator_round1026.py::
  TestBounds::test_forbidden_paths_out_of_diff. На base 8c035908 оба тоже
  failed; D4-B их не трогает; не D4-B regression.
- **Mutation (independent):** в disposable worktree @ b6d7064c
  `_local_bytes_verified` dirty check заменён на `if False:`;
  pytest -k dirty_snapshot -> **1 failed, 57 deselected**
  (`test_dirty_snapshot_is_never_verified`, assert verified=False).
  Restore `git checkout` -> **58 passed**, worktree чистый, удалён.
- F8: tools/gen_param_registry_round1025.py --check ->
  **CHECK OK: реестр 644 == REGISTRY**; карта полна, TSV/map идемпотентны.
- Полный suite не запускался; фокус bounded.

## 5. Regression/совместимость

- GitHub default: 610 включает test_evol_source_reader и сторонние кейсы;
  third-party stub -> provider=github/host=github.com; local marks отсутствуют.
- tool_router reuse: local answer сохраняет provider/host/local_source_
  verification/note и repo:// ссылку; GitHub reuse defaults прежние.
- config key: flags.self_diag_repo_origin non-secret, global_only, per_chat
  false, tab mod_checkup; F8 644; no new page/store/DB.
- settings: ClassVar SELF_DIAG_LOCAL_REPO_ROOT, default "", no dataclass field
  delta; prompts/models/handlers/checkup/checkup_service/web/.gitignore
  unchanged (diff).
- No shell/network/import/exec in local path; no host paths/secret in payload;
  tests + direct probes.


## 6. Строки D4-B

- **SD1-D4-01 - partial:** local provider и exact-owner routing есть;
  сторонний GitHub путь сохранён тестами; реальный live GitHub не выполнялся.
- **SD1-D4-03 - partial:** канонический repo_origin в существующем каталоге/
  hot/default/normalize/global_only; событие old/new/by=config; actor остаётся
  в существующей строке `[api] config updated`, отдельного аудита нет.
- **SD1-D4-04 - no live:** локальный путь без auth/token; payload без секретов;
  живой прогон не выполнялся.
- **SD1-D4-13 - unit:** denylist и реальные чтения/листинг; приватные
  config/secrets/backups/.git paths не возвращаются; тесты/прямые probes.
- **SD1-SEM-04 - unit/hermetic:** third-party repo не уходит в Adminbot;
  local только exact owner/name; отдельный live third-party - D4-C.
- **SD1-AC-17 - hermetic only:** существующий GitHub source_reader не
  регрессировал на 610; реальный сторонний GitHub - live/D4-C.
- **SD1-D4-07 - partial:** локальное чтение и local_unverified есть;
  verified_deployed-ветка требует D6 `process_started_at=status.started_at`.
- D4-A rows (D4-05/06/08/12) не регрессировали; D4-B их не менял.
- D6: explicit чекап, recent_commits, user-контент, trace correlation, лог
  `[checkup] identity`, аутентифицированный UI, D2-29b; prompts не менялся.
- D4-C/D7/live: D4-09/10/14, AC-03/06/17, реальный GitHub и production manifest.


## 7. Production / DevOps

- `SELF_DIAG_LOCAL_REPO_ROOT` default ""; локальный provider выключен, пока
  DevOps/unit не задаст корень; до этого поведение GitHub-only.
- Production `.deploy/release.json` отсутствует; identity честно
  `local_unverified`; verified_deployed только после DevOps manifest и D6
  process_started_at. Это допустимо D4-08, но не DONE.
- `.gitignore:7` `deploy_*.py`: `services/source_reader.py` не матчится,
  `services/deploy_identity.py` tracked; release path `git checkout` включает.
  Классификация BACKLOG/D4-B + DevOps, не блокер; позже `/deploy_*.py`
  или `!services/deploy_identity.py`.
- `git log` timeout -> `git_unavailable` (не `git_timeout`) - BACKLOG.

## 8. Три опоры

- **Implementation:** прочитаны contract v1.1 section 2.4/3/4,
  LocalSnapshotProvider, SourceReader routing, repo_origin helpers,
  tool_router reuse, settings ClassVar, tests/binding; diff 65 files
  vs D4-A base; expected core changes; existing handlers/checkup,
  checkup_service, prompts, models, web, DB, .gitignore не тронуты.
- **Test validity:** 58/610 passed; assertions прочитаны; pre-existing RED
  identical on candidate and base; dirty mutation red/restore green;
  F8 CHECK OK 644; tests strong for claims, but no test for list_tree map
  limits / self-query parenthetical - residual notes.
- **Independent challenge:** direct path_is_denied cases; provider read
  credentials/cookies/.git/deploy/ADS/symlink/root missing; self-read allowed;
  dirty verified=false; own local vs third-party GitHub; repo_origin token
  stripped; per_chat=false; SELF_DIAG_LOCAL_REPO_ROOT=""; mutation observed.


## 9. Остаточные ограничения

- `list_tree` has a hard 20_000-entry guard and skips tool dirs; it does not
  apply existing SOURCE_READ_MAX_FILES/DEPTH to the map. Contract section 3.2
  says map by existing limits. Content reads are bounded by max_files/
  `_MAX_LOCATOR_PATHS`; no secret/read bypass. Recommend Architect/PM clarify
  in D4-B/D6; not treated as a D4-B behavioral blocker.
- Contract section 3.1 parenthetical «question about itself without explicit
  repo» is not wired into SourceReader discovery; exact owner/name local works;
  self-query remains D4-01 partial/D4-C. Not hidden as verified.
- `repo_origin` event actor is in existing API line, not in the event; D4-03
  partial; no separate audit store (by design).
- reuse scope by GitHub token (local answer with token goes chat-scope) -
  conservative BACKLOG; ~3 identity calls per local read - D6 budget.
- linked worktree `.git` gitdir outside root -> path_denied; production normal.
- UI/Playwright/Browser Use not applicable; no UI changes.

## 10. Итог

**Approved для D4-B (unit/preprod).** D4/self-diag DONE не объявляются;
B1/B2/B3 D4-A фиксы не регрессировали; D4-B rows above remain partial where
live/manifest/D6 is required. Reviewer не менял код/настройки/прод; mutation
worktree удалён; provided worktree чист от кодовых изменений; карта и
progress_scope не менялись.

