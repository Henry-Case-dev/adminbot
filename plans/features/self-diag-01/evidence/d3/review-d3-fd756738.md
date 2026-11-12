# D3 - независимое ревью probes/collector/bundle

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code fd7567388c9629692ca999301385dbda42bec842, docs a4d2b5b85c819f1d9c314f97e2a89814750c445f.
База: approved D4-B 722ccfc522ba00a18dc74881913020151ac250aa.
Worktree: self-diag/d3, ...-573654bd.

**Вердикт: Needs Fixes.** Найден secret leak: `config.effective` возвращает raw
`flags.self_diag_repo_origin`; URL с userinfo/token попадает в bundle/tool page.
D3/self-diag DONE не объявляются; EVD-12 не REVIEW; EVD-14 зависит от этого
источника. Карта/progress_scope не менялись; продуктовый код/настройки/прод
не менялись; деплоя нет.

## 1. Blocker B1 (security, Builder): secret в config.effective

**Требование:** SD1-EVD-12 (redaction, no secret values), SD1-D2-29a
(no secrets в source references), SD1-D2-16/SD1-AC-18 (факты без утечек).

**Факт:** `_CONFIG_KEYS` включает `flags.self_diag_repo_origin`;
`_probe_config_effective` берёт `cache.get(key)` raw и кладёт в
`facts.settings[].effective`. D4-B `normalize_repo_origin` strips userinfo,
но probe его не применяет. `_build` не редактирует facts, только
`observation.redaction` (обычно None); `render_page` отдаёт facts в tool page.

**Точное воспроизведение:** fake ConfigCache.get(KEY) ->
`https://user:SECRET-TOKEN-9988@github.com/Henry-Case-dev/adminbot.git`;
`_probe_config_effective` -> `facts.settings[0].effective` содержит
`SECRET-TOKEN-9988`; `DiagnosticCollector.collect(config.effective)` ->
`PAGE_LEAK=True`, `BUNDLE_LEAK=True`. `render_facts_text` этот список
пропускает, но bundle/tool page и любые иные потребители bundle содержат
токен. `output_projection` known-secret/pattern наборы этот non-secret ключ
не закрывают (repo_origin не secret).

**Минимальный fix:** для `flags.self_diag_repo_origin` использовать
`source_reader.normalize_repo_origin`/`configured_repo_origin` (owner/name,
без userinfo) или применить `ctx.redact` и не отдавать raw URL; добавить
regression test: token в cache -> `bundle/page` без token, значение
`Henry-Case-dev/adminbot`. D6 не требуется. Затрагивает EVD-12/EVD-14.

## 2. Implementation audit

- One `DiagnosticEvidenceBundle`: closed 9 statuses, 5 claim kinds,
  observed_at/source_id/owner/scope/coverage, distinct declared/configured/
  probe_succeeded/healthy, permission_decision, latency/reason, runtime/git/
  deploy fields, stack_summary continuation, existing SourceRef/mca_events; no
  DDL/second DB/LLM.
- Runtime probes: 17 AREAS, 24 built-ins, 11-child incident scenario; fixed
  argv `systemctl show` via `create_subprocess_exec` (no shell); arbitrary
  path/root/unit/sql/chat/user/host/port/token args rejected by
  `DENIED_ARGUMENT_KEYS`/schema; db.integrity expensive only; CPU percent only
  after two real observations; empty journal -> healthy None/reason
  empty_log_window; scenario does not include db.integrity.
- Collector: area/probe/scope/window/cursor/args validation; scenario via
  existing probe registry, no LLM; cache key includes request fingerprint
  (args/scope/chat/permission class/role) + runtime_sha + config token; per-key
  lock dedup; cursor validation; cancelled execute not stored; no write.
- `collect_for_checkup()` uses same collector/probes and provided logs, no
  second journal read; explicit `handlers/checkup.py` unchanged (D6).
- `tool_schemas` adds 17th `inspect_runtime`; `tool_router` dispatch/DI/
  permission/facts/signal/event; D5 did not change these files; D6 must add
  prompt_readback registration and checkup wiring on top, preserving inspect_
  runtime. No conflict in current candidate, but coordination note.
- B1 above is the only defect found; all other inspected claims matched code/
  tests, except boundaries listed in section 6.

## 3. Тесты и mutation

- pytest tests/test_evidence_bundle.py tests/test_diagnostic_probes.py -q
  -> **79 passed**.
- Focused 35-file set из binding -> **1324 passed** (один Starlette/httpx
  warning; no failure lines; shell wrapper exit code not used as proof).
- Assertions прочитаны: closed bundle/status, declared/configured/probe/
  healthy separation, coverage, source id/owner, stack continuation,
  mca_events, 17 areas, CPU two observations, empty journal, db.integrity
  expensive, fixed argv/no shell, timeout/degradation, cache permission
  class, concurrent dedup, cancellation, collect_for_checkup, no LLM/agent.
- **Independent mutation:** в disposable worktree @ a4d2b5b8
  `CollectionRequest.fingerprint` permission_class заменён на None;
  pytest -k permission_class -> **1 failed, 56 deselected**
  (`test_permission_class_is_part_of_cache_key`, assert len(calls)==1 vs 2).
  Restore -> **79 passed**; worktree чистый, удалён.
- Two pre-existing RED подтверждены и на candidate, и на base b6d7064c:
  `test_addtr_tools_minifix.py::test_l1_seam_announce_then_execute_once`
  и `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_
  out_of_diff`; D3 их не исправляет; BACKLOG.

## 4. Independent counterexample

Config secret leak (B1), not Builder case:

- fake ConfigCache.get(flags.self_diag_repo_origin) = URL с userinfo/token;
- `_probe_config_effective` facts: token в `effective`;
- `DiagnosticCollector.collect(config.effective)`: `PAGE_LEAK=True`,
  `BUNDLE_LEAK=True`; status ok;
- `render_facts_text` skips nested list (`False`), but bundle/tool page и
  scenario/other consumers остаются небезопасными.

Другие проверки: `path`/`unit`/`sql`/`chat_id`/`user_id` args rejected;
empty journal -> healthy None; CPU first derived=false/second true; scenario
does not run db.integrity; cache permission mutation red; no shell/DB write.

## 5. Строки D3

**После B1 fix могут быть REVIEW (unit evidence):**
- D3-01..D3-08 (typed tool, separated states, 17 areas, registry, CPU,
  incidents watchdog, validation, injection-as-data).
- EVD-03, EVD-04, EVD-05, EVD-06, EVD-07, EVD-08, EVD-09, EVD-10, EVD-11,
  EVD-13, EVD-15, EVD-17, EVD-18, EVD-19 (unit), SEM-01, SEM-03, SEM-06,
  SEM-07, SEM-11, SEM-12, AC-04 (shared collector), AC-05, AC-18, AC-20
  (local timeout/degradation; external live is D4/live).
- EVD-14 scenario facts unit-covered, but its `config.effective` source
  contains B1 token until fix; cannot REVIEW now.

**Blocked/PENDING сейчас:**
- **EVD-12 FAILED**: redaction does not cover raw `repo_origin` URL; bundle/
  tool page leak token (B1).
- **EVD-14 partial/blocked** by same config source; scenario otherwise covered.
- **EVD-01 PENDING**: explicit checkup handler wiring is D6; only
  `collect_for_checkup()` seam and tool-path shared collector proven.
- **SEM-08 PENDING/live**: no live-LLM context-following proof; only
  structural absence of keyword routing.
- D6: UI/analytics, inspect_runtime rendering; commits_since_deploy remains
  None; linked worktree deploy.identity path_denied; EVD-19 restart and AC-20
  external timeout/429 live remain D6/D7/live.
- D3/self-diag DONE not declared.

## 6. D6 integration / seams

- Explicit `handlers/checkup.py` unchanged; D6 must call `collect_for_checkup()`
  and not create a second collector; EVD-01 stays PENDING until then.
- `inspect_runtime` is the 17th tool in `tool_schemas`/`tool_router`; D5 did not
  modify those files, D6 must add `prompt_readback` registration and checkup
  wiring on top, preserving the 17th. No conflict in current candidate;
  write-scope coordination note for D6.
- D6 UI/analytics: `inspect_runtime_called` event exists only in existing
  `mca_events`; no page rendered. No new page/store/DDL/flags.
- `commits_since_deploy` remains None until D6 passes `status.started_at`;
  linked worktree identity path_denied; platform live D7.

## 7. Backlog

- BACKLOG_ONLY: two pre-existing RED (addtr L1 seam, tool_coordinator
  forbidden paths) confirmed on candidate and D4-B base; D3 not responsible.
- BACKLOG_ONLY: `inspect_runtime` not in `tool_result.TOOL_CATEGORIES`
  (default external_read); conservative, no D3 defect.
- BACKLOG_ONLY: inspect_runtime analytics UI and mca event rendering D6.
- B1 config leak is IN_SCOPE, not backlog.
- CRITICAL_OUT_OF_SCOPE: none separately found; B1 is in-scope security.

## 8. Three pillars

- **Implementation:** read evidence_bundle, runtime_probes (17 areas/24
  probes/incident scenario), diagnostic_collector, memory_health diff,
  tool_schemas/tool_router diffs; checked closed statuses/claims, separated
  states, stack, SourceRef/mca_events, fixed argv/no shell, db.integrity
  expensive, cache/dedup/cancel, collect_for_checkup.
- **Test validity:** 79/1324 passed; assertions behavioral; mutation cache
  permission class red/restore 79; pre-existing RED identical on base;
  test gaps: no config-token redaction test (B1), no live.
- **Independent challenge:** config token leak bundle/page (B1); args
  path/unit/sql/chat/user rejected; empty journal healthy None; CPU two
  observations; db.integrity expensive; mutation observed.

## 9. Residual / live

- No deployment/live VPS/TG/journald/systemd/PSI/DNS/GitHub/Telegram checks;
  probes read real sources only in production; stub/local SQLite tests.
- `collect_for_checkup()` not wired to explicit checkup (D6); D6 must use same
  collector and not read journal twice.
- UI/Playwright/Browser Use not applicable to D3 (D6 analytics).
- `commits_since_deploy=None`; linked-worktree deploy identity path_denied;
  D4-C/live provenance.
- `requirements_gate --stage review --slice D3 --candidate fd756738` returns
  candidate mismatch/all PENDING; PM map/evidence sync, not D3 code defect.
- Reviewer did not edit map/progress_scope/product/settings/prod; mutation
  worktree removed; provided worktree clean except review artifact; no deploy.

## 10. Итог

**Needs Fixes.** Fix B1 before D3 approval; EVD-12 FAILED and EVD-14 blocked
until then. After B1, the listed D3 unit rows can be REVIEW, with EVD-01 D6,
SEM-08 live, D6 UI/analytics, commits_since_deploy None, linked-worktree
path_denied and D7/live still open. D3/self-diag DONE not declared.

