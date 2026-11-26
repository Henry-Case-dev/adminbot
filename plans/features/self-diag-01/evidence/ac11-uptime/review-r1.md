# SELF-DIAG AC-11 / D6-12 — независимое ревью исправления (r1)

**Ревьюер:** `ses_dea861824ffeu1NBvspR5ZtCb4` (независимая сессия).
**Кандидат:** `8816dc1d11abe8dcd1971be9b65ff838b7acb10c`, ветка `fix/selfdiag-ac11-uptime` (запушена), один коммит над базой.
**База:** `b5bb71c7a6e89bbf13de88b6f013725dcf633563` (2.58.252, deployed).
**Изменённые файлы (5):** `web/api/prompt_access.py`, `web/api/routes.py`, `services/status_service.py`, новый `tests/test_selfdiag_ac11_config_uptime.py`, evidence `plans/features/self-diag-01/evidence/ac11-uptime/README.md`. Вне этих файлов изменений нет.

## Вердикт: APPROVED_FOR_RELEASE_PREPARATION

Оба дефекта закрыты и подтверждены независимо: RED воспроизведён на чистом архиве базы
(3 failed / 4 passed — ровно `user`, `moderator`, uptime), GREEN на кандидате (7 passed);
дизайн — одно правило (`ChatResources.visible` на `chat_param_matrix` с пустым `chat_root`),
второго разбора матрицы нет; non-prompt настройки не сужены; чатовая ветка не изменена.
Блокирующих находок нет. Non-blocking: статически найденный пре-существующий обход
`perm_overrides` в `GET /api/config/overrides-map` (чат-скоуп, не AC-11) и устаревший
docstring `speech._resource_allowed` («паритет с GET /api/config» больше не верен).

```json
{
  "artifact": "plans/features/self-diag-01/evidence/ac11-uptime/review-r1.md",
  "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
  "candidate": "8816dc1d11abe8dcd1971be9b65ff838b7acb10c",
  "base": "b5bb71c7a6e89bbf13de88b6f013725dcf633563",
  "base_version": "2.58.252",
  "branch": "fix/selfdiag-ac11-uptime",
  "commits_above_base": 1,
  "changed_files": ["web/api/prompt_access.py", "web/api/routes.py", "services/status_service.py", "tests/test_selfdiag_ac11_config_uptime.py", "plans/features/self-diag-01/evidence/ac11-uptime/README.md"],
  "scope_check": "git diff --name-status b5bb71c7a..HEAD = 5 files (3 code, 1 new test, 1 evidence); no DDL/flags/endpoints/frontend changes; git status clean",
  "ac11_closure": {
    "status": "CLOSED",
    "defect": "GET /api/config without X-Chat-Id returned full prompt text to user and moderator (global branch filtered only spec.secret)",
    "red_on_base": "clean git archive b5bb71c7a + the new test file: 3 failed, 4 passed — test_plain_user_gets_no_prompt_value_or_key (item with value), test_moderator_gets_no_prompt_value_or_key, test_uptime_is_non_null_and_matches_status (None is not None)",
    "green_on_candidate": "7 passed",
    "independent_probe": "member and moderator without a chat: guarded keys in /api/config items = 0 (124 items each); the prompt marker value is absent from the body; global admin: 27 guarded prompt keys, target value exact; a moderator with DB view_roles ['moderator'] grant gets the value (intended explicit grant)",
    "non_prompt_untouched": "member still receives limits.checkup_max_symbols = 1200",
    "chat_branch_unchanged": "local_admin + default matrix sees the key; the same actor with perm_overrides view_roles ['moderator'] does not"
  },
  "d6_12_closure": {
    "status": "CLOSED",
    "defect": "/api/status/self-diagnosis runtime.uptime_seconds = null (ISO string subtracted from datetime, TypeError swallowed)",
    "red_on_base": "same base run: assert None is not None at the uptime test",
    "green_on_candidate": "uptime_seconds is a non-empty int (~3600 with an artificial start one hour back), abs(diag - /api/status bot.uptime_seconds) <= 2.0, runtime.started_at equals the patched ISO string",
    "single_parse_point": "services.status_service._parse_started_at is the only parser of status.started_at; /api/status itself computes uptime from started_monotonic (unchanged JSON contract)",
    "edge_cases": "Z / lowercase z / +03:00 / naive / space separator / datetime aware+naive parse correctly to aware UTC; empty, malformed, None, int -> None (uptime null, no crash); started_at_dt() returns None for absent/malformed",
    "timezone": "naive is treated as UTC, matching deploy_identity._parse_datetime (same contract, cited in the docstring); offset values are normalized to UTC"
  },
  "design_judgement": {
    "one_rule": "global_resources(ctx, db_overrides) returns the same ChatResources with chat_root={}; visible() -> hidden check + access.can_view_param on access.chat_param_matrix(key, db_overrides, {}) — the same assembly the chat branch uses, only without chat perm_overrides. No second matrix parser or manual comparison.",
    "guarded_predicate": "prompt_text.guarded_key = prefixes ('prompts.', 'character.', 'style.'); all 29 registry keys of category prompts match; no prompts-category key falls outside; hidden prompt keys are already excluded by spec.hidden before the guard (pre-existing).",
    "scope": "the guard lives only in the global branch (chat path unchanged) and only for guarded_key keys; secrets/limits/flags/content/models keep the previous global behaviour.",
    "non_prompt_matrix": "default_matrix() for category prompts = view_roles ['local_admin']; user/moderator are not eligible globally, local_admin/custom rank>=3 are (same eligible_type rule as the chat path)."
  },
  "remaining_disclosure_probes": {
    "speech_surface_global": "member and moderator GET /api/speech/block/summary.base.narrator, /api/speech/blocks, /api/speech/core, /api/speech/style without a chat -> 403 'нет доступа к речи' (the persona-view gate requires global admin or edit_persona); global admin -> 200. Not a role-wide disclosure; the builder's declared boundary is limited to persona-editor roles.",
    "prompt_history_global": "member and moderator GET /api/prompts/{key}/versions without a chat -> 403 'нет права на историю промпта' (decide: admin or explicit edit grant)",
    "params_meta": "/api/config/params-meta returns metadata only (per_chat/group/title/type/secret_mask), no values; marker absent",
    "overrides_map": "member -> 403; moderator without chat grants -> 200 with empty items; static code read shows per-chat prompt override values are returned to a chat local_admin/moderator without consulting perm_overrides (pre-existing D07 surface, not AC-11) — backlog F01",
    "invalid_chat_header": "X-Chat-Id=abc -> 422; X-Chat-Id=0/123/foreign chat -> 403; no path falls back to the unguarded global response",
    "hidden_doc_keys": "character.*/style.* have no catalog spec and no bot_settings rows, so they never appear in /api/config (admin response contains only the 27 visible prompts.* keys); the guard still covers them if they ever appear"
  },
  "mutations": [
    {"id": "M1", "change": "remove the global guarded_key guard", "result": "2 failed / 5 passed (user, moderator)", "restored": true},
    {"id": "M2", "change": "restore ISO subtraction in _self_diag_payload", "result": "1 failed / 6 passed (uptime None is not None)", "restored": true},
    {"id": "M3", "change": "narrow every key instead of guarded_key keys", "result": "1 failed / 6 passed (non-prompt limits narrowed for user)", "restored": true},
    {"id": "M4", "change": "ignore db_overrides in global_resources", "result": "1 failed / 6 passed (explicit grant no longer reveals)", "restored": true}
  ],
  "mutations_restored_sha256": {"web/api/routes.py": "677bef0bf37f60aff8649c72b35de05b8e217fc6fb50533bd9ee8b1258645719"},
  "control_hashes": {"web/api/routes.py": "677bef0bf37f60aff8649c72b35de05b8e217fc6fb50533bd9ee8b1258645719", "web/api/prompt_access.py": "feea2535e228e5245f250790d3ad68a8f299ba9167b4084c7fd11afa09486bfd", "services/status_service.py": "620b9b7c90b1e4c807d6da6c3c120e065255220a79c8fd6a5171fa25cae1f2fd"},
  "tests": {
    "new_test": "7 passed on the candidate; uses real handlers (TestClient over create_app + real RBAC on a fake PG), real /api/config and real get_status/get_status_self_diagnosis",
    "m1c_lock": "124 passed (prompt_chat_acl + prompt_text_invariant + m1_predicate)",
    "checkup_contract": "41 passed",
    "status_service": "43 passed",
    "acl_gate_and_readback": "95 passed",
    "adjacent_suites": "176 passed (global_config_optimistic 5, asap8_v6_d07_overrides 11, diagnostic_probes 70, m4c_acl_hardening 63, m2_runtime_edges 17, asap8_v6_c06a_status_ui 5, asap5_random_bootstrap_config 5)",
    "js_suite": "not run: no frontend file changed"
  },
  "base_red": {
    "prompt_field_audit": "1 failed / 29 passed on candidate and on base (test_every_editable_prompt_has_reachable_surface: hidden prompts.direct_chat_synthesizer_system_prompt outside the catalog)",
    "m4_module_params": "1 failed / 15 passed on candidate and on base (test_js_fixture_matches_live_contract)",
    "status_section_ui_merge": "1 failed / 6 passed on candidate and on base (test_mode_version_line_removed)",
    "deploy_identity_d4c": "22 passed on candidate and on base in the real worktrees, and also in a clean .git-less archive; the builder's 17 failed/5 passed (environment) did not reproduce here and is not a product failure on either side",
    "identical": true
  },
  "findings": {
    "blocking": [],
    "backlog": [
      {
        "id": "SD-AC11-R1-F01",
        "class": "BACKLOG_ONLY",
        "title": "GET /api/config/overrides-map returns per-chat prompt override text without perm_overrides check",
        "evidence": "web/api/routes.py config_overrides_map: spec.per_chat/hidden/secret filter + chat_admin/DM access, but no chat_param_matrix/can_view_param; applies to the 29 per_chat prompt keys",
        "impact": "a chat local_admin/moderator whose perm_overrides deny a prompt still sees the chat override value in this D07 surface; pre-existing, chat scope, not introduced by this candidate and not the AC-11 defect",
        "disposition": "separate small fix: apply the same resource matrix to per_chat prompt keys in overrides-map (or explicitly narrow the key list)"
      },
      {
        "id": "SD-AC11-R1-F02",
        "class": "BACKLOG_ONLY",
        "title": "Stale docstring in web/api/speech.py::_resource_allowed",
        "evidence": "the docstring still says 'В глобальном скоупе решение не сужает ... паритет с GET /api/config', while the global /api/config now narrows prompt text via global_resources",
        "impact": "documentation contradicts the shipped rule and could re-justify a future global widening; no runtime effect",
        "disposition": "update the docstring together with the overrides-map fix"
      }
    ]
  },
  "deployability": {
    "as_slice": "ONE commit over deployed b5bb71c7a; safe to release-preparation as a small fix release",
    "release_prep_required": "version bump APP_VERSION (2.58.253), release branch/assembly, manifest dry-run at the final code tip with previous ffdc6eadf/2.58.252",
    "rollback": "code-only to b5bb71c7a; no DDL/migrations/flags"
  },
  "required_postdeploy": [
    "Manifest: deployed_sha == actual deployed SHA, previous_sha b5bb71c7a, previous_version 2.58.252, version == bumped version, dirty_tracked false.",
    "Read-only /api/config as a plain user and as a moderator WITHOUT X-Chat-Id: no prompts.* keys, no prompt text; the same call as global admin returns the prompt values.",
    "Read-only /api/status/self-diagnosis: runtime.uptime_seconds is a non-null int close to /api/status bot.uptime_seconds; runtime.started_at is the same ISO string as /api/status.",
    "Served blobs for web/api/routes.py, web/api/prompt_access.py, services/status_service.py equal the built release; healthz 200; schema unchanged; disk audit/cleanup keep policy.",
    "Restricted-chat regression spot check: chat-scope /api/config still hides prompt keys per perm_overrides; global prompt history still 403 for user/moderator."
  ],
  "reviewer_session": "ses_dea861824ffeu1NBvspR5ZtCb4"
}
```

## 1. Воспроизведение RED/GREEN

RED — чистый `git archive b5bb71c7a` в `%TEMP%`, поверх скопирован новый тест:
`3 failed, 4 passed` — ровно `test_plain_user_gets_no_prompt_value_or_key` (в item реально лежал
`AC11-PROMPT-MARKER`), `test_moderator_gets_no_prompt_value_or_key`,
`test_uptime_is_non_null_and_matches_status` (`assert None is not None`).

GREEN — кандидат: `7 passed`. Тесты идут через реальные обработчики (`TestClient(create_app(cache))`
для `/api/config`; прямые `routes_mod.get_status` / `get_status_self_diagnosis` для статуса), реальный
HMAC `X-Telegram-Init-Data`, реальный RBAC; двойники — только хранилище (роли/гранты/`bot_settings`),
как в соседних ACL-наборах. Переопределён только `diagnostic_policy.decide` (гейт, который дефект не
затрагивает).

## 2. Дизайн AC-11

`global_resources(ctx, db_overrides)` — это тот же `ChatResources`, что и в чате, с `chat_root={}`:
`visible()` = hidden → только глобальный админ, иначе `can_view_param` на
`chat_param_matrix(key, db_overrides, {})`. Второго разбора матрицы нет; чатовая ветка использует
`chat_resources`, глобальная — `global_resources`, правило одно.

Guard стоит только в глобальной ветке и только для `prompt_text.guarded_key(key)`
(`prompts.`, `character.`, `style.`). Все 29 ключей реестра категории `prompts` попадают под префикс;
ключей категории `prompts` вне префиксов нет. Секреты/limits/flags/content/models сохраняют прежнюю
глобальную семантику — подтверждено тестом (`limits.checkup_max_symbols = 1200` у `user`).
Скрытые ключи отсекаются прежним `spec.hidden` до guard'а.

## 3. Uptime D6-12

`_parse_started_at` — единственная точка разбора `status.started_at`; `/api/status` по-прежнему считает
аптайм от `started_monotonic`, его JSON-контракт не менялся (`started_at` остаётся ISO-строкой).
Разбор: `Z`/`z`/`+03:00`/naive/space/datetime → aware UTC; пустое/битое/None/int → `None`
(аптайм `null`, без исключения). Naive трактуется как UTC — ровно контракт
`deploy_identity._parse_datetime`, на который ссылается docstring.

## 4. Мутации

| # | Мутация | Результат | Восстановление |
|---|---------|-----------|----------------|
| M1 | убран глобальный guard | 2 failed / 5 passed (user, moderator) | sha256 `677BEF0B…5719` |
| M2 | возвращено вычитание ISO-строки | 1 failed / 6 passed (uptime None) | `677BEF0B…5719` |
| M3 | сужены ВСЕ ключи (без guarded_key) | 1 failed / 6 passed (limits у user) | `677BEF0B…5719` |
| M4 | `global_resources` без db_overrides | 1 failed / 6 passed (грант не раскрывает) | `677BEF0B…5719` |

Все четыре восстановлены байт-в-байт; контрольные хэши совпадают с README билдера.
Пропусков/skip в новом тесте нет; существующие тесты не изменялись (name-status — только новый файл).

## 5. Прогоны

* `prompt_acl + invariant + predicate` — **124 passed**; `checkup_contract` — **41**;
  `status_service` — **43**; `acl_gate + prompt_readback` — **95**; смежные 7 наборов — **176**.
* Base-identical: `prompt_field_audit` 1/29 (тот же тест), `m4_module_params` 1/15 (тот же),
  `status_section_ui_merge` 1/6 (тот же) — идентично на базе; `deploy_identity_d4c` — 22 passed и на
  кандидате, и на базе в реальных worktree и в чистом архиве без `.git`; 17 failed у билдера
  (окружение) здесь не воспроизвелись и не являются продуктовым падением ни на одной стороне.
* JS не запускался: фронтенд не менялся.

## 6. Остаточные векторы раскрытия (пробы)

* `/api/speech/*` без чата: `user` и `moderator` → **403** «нет доступа к речи» (нужен global admin
  или действие `edit_persona`); глобальный админ → 200. Заявленная билдером граница реально уже,
  чем «любая роль», и к AC-11 (глобальный `/api/config`) не относится.
* `/api/prompts/*` без чата: 403 «нет права на историю промпта».
* `/api/config/params-meta`: только метаданные, значений нет.
* `X-Chat-Id=abc` → 422; `0`/чужой чат → 403; fallback в незащищённый глобальный ответ невозможен.
* `character.*`/`style.*` не имеют записи каталога и строк в `bot_settings` → в `/api/config` не
  появляются (в ответе админа только 27 видимых `prompts.*`); guard покрывает их на будущее.
* **F01 (backlog):** `GET /api/config/overrides-map` отдаёт значения per-chat override для
  per_chat-ключей (включая 29 prompt-ключей) по chat-гранту/DM, но не применяет `perm_overrides`.
  Это пре-существующая D07-поверхность, чат-скоуп, не AC-11; проверено чтением кода (в фейковом
  хранилище SQL даёт пусто, поэтому runtime-проба не воспроизводит условие).

## 7. Deployability и постдеплой

Кандидат — один коммит над deployed `b5bb71c7a`, продуктовые изменения только в трёх файлах, без
DDL/флагов/эндпоинтов/фронтенда. Готов к release-preparation (bump версии, release branch/assembly,
manifest на финальном код-типе с previous `ffdc6eadf`/2.58.252). Постдеплой-гейт: манифест с
фактическим SHA; read-only `/api/config` без чата у `user`/`moderator` — ни ключей `prompts.*`, ни
текста, у глобального админа — значения; `/api/status/self-diagnosis` — ненулевой int аптайма и та же
ISO-строка `started_at`, что у `/api/status`; served blobs трёх файлов; healthz/schema/disk.

## 8. Ограничения

Живой Telegram/WebView не использовался (TestClient + реальный HMAC/RBAC на фейковом PG); реальный
прод не запрашивался. Допуск аптайма 2 с — из-за monotonic (`/api/status`) vs wall-clock
(self-diagnosis). Сценарий F01 (overrides-map с реальным `perm_overrides` и per-chat prompt override)
проверен статически, не runtime. Глобальная `/api/speech/*` граница осознанно не сужена и остаётся
поверхностью ролей с `edit_persona`.

## 9. Гигиена

Ревью — read-only: продуктовые файлы и тесты не изменялись; артефакт — единственный untracked файл.
Временные архивы/скрипты в `%TEMP%\opencode\sd-ac11` удалены; мутации восстановлены (sha совпал).
