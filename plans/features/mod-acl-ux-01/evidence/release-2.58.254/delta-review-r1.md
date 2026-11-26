# MAC-S4-172 egress — delta-ревью релиза 2.58.254 (r1)

**Ревьюер:** `ses_dea861824ffeu1NBvspR5ZtCb4`.
**Кандидат:** `fb3f2d2216da829dc0bef3cfdc5a6cb17686fdb1` (ветка `release/mod-acl-egress-2.58.254`, запушена; дерево `7ebdac7d3`; код-тип `de5f6cd0f`).
**База:** `54546ab5b201a5d8bd169bad613e730d371fc3b9` (2.58.253).
**Срез:** `443a1eb76`, tree `f5ae3f24c`, ревью r2 sha256 `71370327…a8fba` (APPROVED_FOR_RELEASE_PREPARATION).

## Вердикт: NEEDS_FIXES

Продукт, срез, bump, guard и тесты в порядке: resume-ответ идёт через chokepoint, страж
allowlist-модуля на месте, routes.py не менялся и пин не двигался, version wave — только версии,
тесты и base-identical падения подтверждены. Единственный блокер — **evidence/manifest**:
закоммиченный `manifest-dry-run-final-tip.txt` и §7 assembly называют «итоговым tip» `60684c0dd`,
тогда как фактический финальный HEAD — `fb3f2d221` (тот самый коммит, который добавил этот файл).
Мой dry-run на `fb3f2d221` даёт `deployed_sha fb3f2d221`, previous `54546ab5b`/2.58.253 — то есть
записанное «final tip» значение устарело на один docs-коммит и противоречит и handoff-claim, и
финальному SHA. Правка evidence-only: перегенерировать dry-run на `fb3f2d221` и обновить assembly
§7 + test-output, либо явно объявить записанный `60684c0dd` pre-evidence снимком и deploy-target
`fb3f2d221`.

```json
{
  "artifact": "plans/features/mod-acl-ux-01/evidence/release-2.58.254/delta-review-r1.md",
  "verdict": "NEEDS_FIXES",
  "deployed_sha": "fb3f2d2216da829dc0bef3cfdc5a6cb17686fdb1",
  "tree": "7ebdac7d3296055a606132295239b1e0176319dc",
  "code_tip": "de5f6cd0fdb74f81a3a45236670d2f0300180fc0",
  "base": "54546ab5b201a5d8bd169bad613e730d371fc3b9",
  "base_version": "2.58.253",
  "branch": "release/mod-acl-egress-2.58.254",
  "commits_above_base": 6,
  "merges_above_base": 0,
  "slice_identity": {
    "slice_tip": "443a1eb764fcd3ce21d12545691f5ad8f812b6c5",
    "slice_tree": "f5ae3f24c0c9ddacc6d02ba54be246f3b063a002",
    "cherry_pick_commit": "1368056bb",
    "cherry_pick_tree_equals_slice": true,
    "slice_files": 22,
    "slice_files_detail": "19 new (18 evidence + new test), 3 modified",
    "product_test_blobs_at_tip": {"services/telegram_send.py": "2759d2ac2681", "services/direct_chat_service.py": "2af124d1cbd3", "tests/test_outgoing_guard_round1022.py": "171b36da2744", "tests/test_mod_acl_ux_01_s4_172_egress.py": "b4c9f32372b7"},
    "tip_vs_slice": "32 version-wave + 11 docs (review-r2 + 10 release evidence); no product/test drift"
  },
  "product_delta": {
    "resume_path": "resume_deferred_evidence -> _tg_send.send_text (chokepoint); probe on assembled tip: secret masked, chat 10, reply 5, exactly one send",
    "guard_strict": "SEND_ALLOWLIST_NO_BARE_SENDS = {services/direct_chat_service.py}; WRAPPER_ALIASES = (telegram_send, _tg_send, _telegram_send); _bare_sites(direct_chat_service) == []",
    "module_inventory": "direct_chat_service: 4 send primitives, all wrappers (_tg_send.send_rich_message x1, _tg_send.send_text x3), 0 bare",
    "bypass_attempts": "factcheck_orchestrator's other persona_short_reply path uses send_chunked_reply; mca_vision resume uses the registered handler (wrapped); handlers/direct_chat uses _reply (smartmodule_utils -> send_text); no new raw model-text path found; only the known dynamic-dispatch guard limitation (r2 backlog) remains"
  },
  "routes_and_pins": {
    "routes_diff": "0 files",
    "routes_sha256": "677bef0bf37f60aff8649c72b35de05b8e217fc6fb50533bd9ee8b1258645719",
    "pin_constant": "677bef0b… (unchanged)",
    "repin_commit": "none; f8 registry diff is only the APP_VERSION assert 2.58.253->2.58.254",
    "stale_duplicate": "tests/test_mca23_planned_vs_actual.py untouched, fails identically on base"
  },
  "bump": {
    "commit": "de5f6cd0f",
    "wave": "32 files / 35 insertions / 35 deletions",
    "content": "all 35 line pairs are version-only (31 literal + 4 JS regex + settings APP_VERSION line)",
    "reversal": "pre-bump files equal base (0 diff vs 54546ab5b) -> reversing the wave yields base bytes 32/32",
    "bom_crlf": "config/settings.py BOM, 3665 CRLF / 0 bare LF, APP_VERSION = 2.58.254",
    "derived": "param_catalog/pg_db/database/models/migrations/TSV/maps/fixtures 0 diff; gen_param_registry --check CHECK OK",
    "openapi": "221 paths / 261 operations"
  },
  "manifest": {
    "status": "MISMATCH",
    "recorded_final_tip": "60684c0ddaadb2b9c4273ae7b6ee1b258f2869d3",
    "actual_final_head": "fb3f2d2216da829dc0bef3cfdc5a6cb17686fdb1",
    "my_dry_run_at_head": {"deployed_sha": "fb3f2d2216da829dc0bef3cfdc5a6cb17686fdb1", "previous_sha": "54546ab5b201a5d8bd169bad613e730d371fc3b9", "previous_version": "2.58.253", "version": "2.58.254", "dirty_tracked": false, "release_branch": "release/mod-acl-egress-2.58.254", "schema": 1},
    "assembly_claim": "§7 says a re-run 'на итоговом tip (проверенный checkout 60684c0dd)' gives 60684c0dd; the commit fb3f2d221 adds that transcript after the fact, so the real final tip is fb3f2d221",
    "note": "release_manifest.py sets deployed_sha = git rev-parse HEAD; deploying fb3f2d221 and writing the manifest there yields fb3f2d221. The committed evidence must record that (or explicitly name the deploy target and label the 60684c0dd snapshot)"
  },
  "tests": {
    "new_egress": "22 passed",
    "guard": "27 passed / 1 failed (meme_command registry gap, identical on base)",
    "m1c_lock": "124 passed",
    "log_telemetry_readback": "114 passed",
    "version_pins_24": "5 failed / 855 passed (same known 5 as base)",
    "known_red_7_files": "candidate 9 failed / 143 passed; base 54546ab5b 9 failed / 143 passed; same names",
    "builder_37_36": "documented 6 failed / 1372 passed vs 6 failed / 1347 passed, FAILED lists identical",
    "py_compile": "changed .py files ok", "diff_check": "trailing whitespace only in test-output *.txt evidence (not code)"
  },
  "base_red": {
    "six": ["test_outgoing_guard_round1022::test_every_send_point_is_registered_or_allowlisted", "test_tool_coordinator_round1026 x2", "test_unified_image_request_round1026 x2", "test_webapp_f9_round1025::test_secrets_count_28"],
    "nine_known_red": ["those under a broader 7-file set plus test_prompt_field_audit, test_mod_acl_ux_01_m4_module_params, test_status_section_ui_merge_round1019, test_mca23_planned_vs_actual"],
    "identical_on_base": true
  },
  "main_checkout": "git status --porcelain --untracked-files=no is empty; no tracked builder edits in the main checkout (untracked tmp_* there are older/unrelated)",
  "probes": {
    "resume_assembled_tip": "masked, chat 10, reply 5, exactly one send",
    "bare_sites": "[] for services/direct_chat_service.py",
    "mutation": "removed chat mask from _maybe_sanitize in a temp archive -> 9 failed (7 chat + 2 resume); restore sha256 telegram_send.py = 81b4cbfe…aeb exact",
    "manifest_head": "dry-run at fb3f2d221 -> deployed_sha fb3f2d221 (previous 54546ab5b/2.58.253)"
  },
  "findings": {
    "blocking": [
      {
        "id": "REL254-R1-F01",
        "class": "IN_SCOPE",
        "severity": "medium",
        "title": "Manifest evidence records the pre-evidence commit as the final tip",
        "expected": "The final-tip manifest dry-run/evidence corresponds to the deployed final HEAD fb3f2d221: deployed_sha fb3f2d221, previous 54546ab5b/2.58.253.",
        "actual": "assembly §7 and test-output/manifest-dry-run-final-tip.txt record deployed_sha 60684c0dd and call it the 'итоговый tip'; the actual final HEAD is fb3f2d221 (the commit that added these docs). My dry-run at fb3f2d221 yields fb3f2d221.",
        "repro": "git rev-parse HEAD = fb3f2d221; cat test-output/manifest-dry-run-final-tip.txt shows 60684c0dd; python tools/release_manifest.py --dry-run at HEAD shows fb3f2d221.",
        "disposition": "Regenerate the final-tip dry-run at fb3f2d221 and update assembly §7 + test-output (one docs commit), or explicitly state that the recorded 60684c0dd is a pre-evidence snapshot and the deploy target is fb3f2d221. Postdeploy gate must assert deployed_sha == actual deployed SHA."
      }
    ],
    "backlog": [
      {"id": "REL254-R1-F02", "class": "BACKLOG_ONLY", "title": "Strict guard cannot see dynamic dispatch", "impact": "partial/getattr/attribute-ref bypass (r2 F01); no current leak; optional AST hardening"},
      {"id": "REL254-R1-F03", "class": "BACKLOG_ONLY", "title": "Unregistered send modules (meme_command, prompt_readback)", "impact": "registry test fails identically on base; static phrases / prompt text, no settings-secret source"},
      {"id": "REL254-R1-F04", "class": "BACKLOG_ONLY", "title": "Evidence test-output files have trailing whitespace (git diff --check rc 2)", "impact": "evidence-only, no product/test code; the builder's 'diff --check clean' claim does not cover these files"}
    ]
  },
  "deployability": {
    "status": "BLOCKED by REL254-R1-F01 (evidence-only); product/code is deployable once the manifest evidence matches fb3f2d221",
    "after_fix": "normal deploy of fb3f2d221 (or the corrected docs tip) with manifest written on the verified checkout; rollback code-only to 54546ab5b"
  },
  "required_postdeploy": [
    "Manifest on the deployed checkout: deployed_sha == actual deployed SHA (fb3f2d221 after the corrected docs commit), previous 54546ab5b/2.58.253, version 2.58.254, dirty false.",
    "Read-only python -c on the deployed checkout: telegram_send._maybe_sanitize('... sk-probe-...') masks the token while an ordinary string with chat id/URL/path is byte-identical; TELEGRAM_SEND_GUARD_ENABLED effectively ON.",
    "Fake-bot resume probe (no network): resume_deferred_evidence with a stubbed persona_short_reply delivers the masked text exactly once to chat 10/reply 5; _bare_sites(direct_chat_service) == [].",
    "Served blobs: services/telegram_send.py 81b4cbfe…, services/direct_chat_service.py 35f04dc2…; healthz 200; version 2.58.254; schema v48; DDL 0; prompt canon/settings digests; disk audit + cleanup keep=2.",
    "Rollback code-only to 54546ab5b (2.58.253); note the rollback intentionally returns the pre-fix egress behaviour."
  ],
  "reviewer_session": "ses_dea861824ffeu1NBvspR5ZtCb4"
}
```

## 1. Lineage и байт-идентичность

6 коммитов над базой, 0 merge. Cherry-pick `1368056bb` даёт дерево `f5ae3f24c`, равное
`443a1eb76`; `git diff --name-only 443a1eb76 1368056bb` пуст. 22 файла среза (19 новых = 18
evidence + новый тест, 3 изменённых). На финальном tip байт-идентичны 4 продуктовых/тестовых blob'а
(`telegram_send.py 2759d2ac…`, `direct_chat_service.py 2af124d1…`, guard-тест `171b36da…`,
egress-тест `b4c9f323…`) и README `5a2c451c…`; отличия tip↔slice — только 32 version-wave и 11
docs (review-r2 + release evidence).

## 2. Продуктовая дельта на собранном tip

Resume-путь идёт через `_tg_send.send_text`; probe на собранном tip: секрет маскируется, chat 10,
reply 5, ровно один send. В `direct_chat_service` 4 отправки, все через обёртки, `_bare_sites` пуст;
строгий набор — только этот модуль. Дополнительные попытки обхода: второй `persona_short_reply` в
`factcheck_orchestrator` доставляется `send_chunked_reply`; `mca_vision` возобновляет через
зарегистрированный обработчик; `handlers/direct_chat` использует `_reply` (обёртка). Нового
модельного send в обход chokepoint не найдено. Остаётся известное ограничение r2: regex-страж не
ловит `functools.partial`/`getattr` (backlog).

## 3. routes/pin и bump

`web/api/routes.py` — 0 diff, sha256 `677bef0b…` = `ROUTES_SHA256_F11`; re-pin не требовался,
в f8 registry изменена только строка версии. `test_mca23` не тронут. Version wave: 32 файла/35
строк, все пары только версии; pre-bump файлы равны базе (0 diff), обратная замена даёт базу 32/32;
BOM/CRLF сохранены; производные 0 diff; registry CHECK OK; OpenAPI 221/261.

## 4. Manifest — блокер

Закоммиченный `manifest-dry-run-final-tip.txt` и §7 assembly фиксируют `deployed_sha 60684c0dd`
как «итоговый tip». Фактический final HEAD — `fb3f2d221` (коммит, добавивший этот файл). Мой
dry-run на `fb3f2d221` даёт `deployed_sha fb3f2d221`, previous `54546ab5b`/2.58.253, version
2.58.254, dirty false. Правка evidence-only: перегенерировать на `fb3f2d221` и обновить assembly
§7/test-output (или явно назвать `60684c0dd` pre-evidence снимком, а deploy-target — `fb3f2d221`).

## 5. Тесты

Новый egress-файл 22 passed; guard 27/1 (meme_command — pre-existing); M1-C 124; log/telemetry/
readback 114; version-pin 24 — 5/855 (те же известные, что на базе); known-red 7 файлов — 9/143
идентично на кандидате и базе; builder'ские 37/36 файлов — 6/1372 vs 6/1347 с одинаковыми FAILED.
Моя мутация (снять чат-маску) — 9 failed (7 chat + 2 resume), восстановление `81b4cbfe…` байт-в-байт.
`git diff --check` чист по коду, но evidence test-output содержит trailing whitespace (не блокер).

## 6. Deployability

После исправления evidence — штатный деплой `fb3f2d221` (manifest пишется на проверенном checkout,
previous 54546ab5b/2.58.253); откат code-only на `54546ab5b`. Постдеплой-гейт: манифест с реальным
SHA; read-only `_maybe_sanitize` (маска `sk-…`, обычная строка байт-в-байт); fake-bot resume probe
(маска, один send); `_bare_sites` пуст; served blobs `telegram_send.py 81b4cbfe…`/
`direct_chat_service.py 35f04dc2…`; healthz/version/schema/DDL; prompt canon/settings digests; disk keep=2.

## 7. Ограничения

Живой Telegram не проверялся (fake bot на границе Bot API); LLM подменялся stub'ом. Полный
37-файловый набор не перезапускался целиком — использованы test-output builder'а + мои прогоны
ключевых наборов и known-red; counts сходятся. Production не затрагивался.

## 8. Гигиена

Ревью read-only: продуктовые файлы/тесты не правились; все мутации/seed — только в temp/untracked
и удалены. Основной checkout: `git status --porcelain --untracked-files=no` пуст (tracked-правок
билдера нет). `%TEMP%\opencode\rel254` будет удалён после снятия артефакта.
