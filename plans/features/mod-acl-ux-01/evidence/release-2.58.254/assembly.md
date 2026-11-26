# Сборка 2.58.254 — MOD-ACL-UX-01 MAC-S4-172 egress (секрет не уходит ни в чат, ни в телеметрию)

- **Роль:** Builder, локальная сборка релиза. **Деплоя, SSH, merge в master,
  force-push нет.** Deploy/effective-state — DevOps после отдельного handoff.
- **База (production 2.58.253):** `54546ab5b201a5d8bd169bad613e730d371fc3b9`.
- **Ветка:** `release/mod-acl-egress-2.58.254` от `54546ab5b`, registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/mod-acl-ux-01-1e46be007668-40924ee6`,
  unit `release-2.58.254`). Интеграция — линейный `git cherry-pick -x`,
  **без merge-коммитов**.
- **Срез:** ветка `feat/mod-acl-s4-172-egress`, tip
  `443a1eb764fcd3ce21d12545691f5ad8f812b6c5`, два коммита поверх той же базы
  (`9b0448db0`, `443a1eb76`). Ревью:
  `…/m1/s4-172-egress/review-r1.md` sha256
  `bbd222ef39cf5012bc4d32fe1257291dd629411cb7195efda8e5042b477ec461`
  (NEEDS_FIXES, `SD172-R1-F01`) и `…/review-r2.md` sha256
  `71370327bfb683d7ed741b8fbc1f63f3481a6cffd8e03964184744c3da4a8fba`
  (**APPROVED_FOR_RELEASE_PREPARATION**, F01 закрыт).
- **Строка:** `MAC-S4-172` (egress-половина: чат + телеметрия). Лог-канал и
  API-ответы заперты M1-B/M1-C и не переоткрывались.

```json
{
  "release": "2.58.254",
  "base": {"sha": "54546ab5b201a5d8bd169bad613e730d371fc3b9", "version": "2.58.253",
           "tree": "be69ba96b8defe525125f54fe0c6e1e8c673ebda"},
  "slice": {
    "branch": "feat/mod-acl-s4-172-egress",
    "source_tip": "443a1eb764fcd3ce21d12545691f5ad8f812b6c5",
    "source_tree": "f5ae3f24c0c9ddacc6d02ba54be246f3b063a002",
    "review_r1": {"artifact": "plans/features/mod-acl-ux-01/evidence/m1/s4-172-egress/review-r1.md",
                  "sha256": "bbd222ef39cf5012bc4d32fe1257291dd629411cb7195efda8e5042b477ec461",
                  "verdict": "NEEDS_FIXES"},
    "review_r2": {"artifact": "plans/features/mod-acl-ux-01/evidence/m1/s4-172-egress/review-r2.md",
                  "sha256": "71370327bfb683d7ed741b8fbc1f63f3481a6cffd8e03964184744c3da4a8fba",
                  "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}
  },
  "integration": "linear cherry-pick -x (2 slice commits) + version wave (1) + this evidence",
  "slice_commits": 2,
  "cherry_pick_commits": ["9d83cdfca5631cec857ab5cbe6fcdd129fc654d3",
                          "1368056bbb1320d44045f3475f3de22bbfe27f62"],
  "pre_bump_head": "1368056bbb1320d44045f3475f3de22bbfe27f62",
  "pre_bump_tree": "f5ae3f24c0c9ddacc6d02ba54be246f3b063a002",
  "bump_commit": "de5f6cd0fdb74f81a3a45236670d2f0300180fc0",
  "bump_tree": "8d0a39ed26be0a901eaf74a64286eb2a4d55ce64",
  "routes_pin_commit": null,
  "code_tip": "de5f6cd0fdb74f81a3a45236670d2f0300180fc0",
  "code_tip_tree": "8d0a39ed26be0a901eaf74a64286eb2a4d55ce64",
  "evidence_commit": "tip of release/mod-acl-egress-2.58.254 (this file + review-r2.md + test-output/)",
  "delta_vs_base_at_code_tip": {"files": 54, "insertions": 973, "deletions": 44}
}
```

`delta_vs_base_at_code_tip` = `git diff --shortstat 54546ab5b de5f6cd0f`:
22 файла среза (19 новых = 18 evidence + новый тест, 3 изменённых) + 32 файла
version wave (пересечений нет: 22 + 32 = 54).

## 1. Порядок интеграции

| # | SHA (новая ветка) | Источник `feat/mod-acl-s4-172-egress` | Tree | Тип |
|---|---|---|---|---|
| 1 | `9d83cdfca` | `9b0448db0` | `d46744a8b` | чат-маска в `telegram_send` + доказанная безопасность телеметрии + 18 evidence + новый тест |
| 2 | `1368056bb` | `443a1eb76` | `f5ae3f24c` | `SD172-R1-F01`: resume-ответ через chokepoint + строгий страж allowlist-модуля |

Cherry-pick выполнен `-x` без правок, авторство и даты коммитов сохранены.
После второго cherry-pick `HEAD^{tree}` = `443a1eb76^{tree}` =
`f5ae3f24c0c9ddacc6d02ba54be246f3b063a002`: **полное дерево** байт-в-байт
равно дереву среза (`git diff --name-only 443a1eb76 1368056bb` пуст).

## 2. Byte identity среза (22 файла)

Срез добавляет 19 файлов и меняет 3. Доказательство сильнее пофайлового:
идентично **всё дерево** (`f5ae3f24c`), поэтому любой файл среза, включая
18 evidence-артефактов и новый тест, равен своему blob'у в `443a1eb76`.

| файл | blob@443a1eb76 | blob@1368056bb |
|---|---|---|
| services/telegram_send.py | `2759d2ac2681…` | `2759d2ac2681…` |
| services/direct_chat_service.py | `2af124d1cbd3…` | `2af124d1cbd3…` |
| tests/test_outgoing_guard_round1022.py | `171b36da2744…` | `171b36da2744…` |
| tests/test_mod_acl_ux_01_s4_172_egress.py | `b4c9f32372b7…` | `b4c9f32372b7…` |

После version wave (`de5f6cd0f`) ни один файл среза не менялся:
`git diff --name-only 443a1eb76 de5f6cd0f` содержит только 32 файла version
wave (список — §3), ни одного файла среза.

## 3. Version wave 2.58.254 (32 файла / 35 строк)

Только версии; коммит `de5f6cd0f`. `git diff --shortstat 1368056bb de5f6cd0f`
→ **32 файла, 35 insertions, 35 deletions** — ровно та же волна, что 2.58.253
(`45b4305cc`), с заменой `2.58.253 → 2.58.254` в тех же 35 строках:
`config/settings.py` — 1 (pin `APP_VERSION = "2.58.254"` + релизная заметка
2.58.254, вставленная в существующую цепочку `Prior …`; 545 символов);
`plans/docs/param-registry-round1025.meta.md` — 1; 4 `tests/js/*` — 4
(regex-пины `2\.58\.254`); 24 py-теста — 25 (23 × 1 +
`test_webapp_round1026_polygon.py` 2); `tools/ui_mod_acl_m4b2_status_e2e.py`
3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1.

**Обратная замена — byte-identical 32/32.** Обратное применение ровно внесённой
дельты (пины `2.58.254 → 2.58.253`, вырезание вставленного сегмента заметки
2.58.254 в `config/settings.py`) дало байты, равные `1368056bb` для всех 32
файлов (скрипт `verify_bump.py`, `reverse==base:True` × 32, `fails=0`).
BOM/переводы строк сохранены: по всем 32 файлам BOM и CRLF/LF-профиль
совпадают с базой (`config/settings.py` — BOM `EF BB BF`, 3665 CRLF + 0 bare-LF
в обеих версиях).

**JS `?v=` — производный, literal-пина нет.** `git grep '?v=[0-9]' web/` →
пусто; в `web/index.html` 18 подстановок `__APP_VERSION__` (из 27 `?v=` в
`web/`), `web/app.py` подставляет APP_VERSION при рендере. JS-сторона
закреплена только четырьмя regex-пинами `tests/js/*`, они и пересчитаны
(`node` → 4/4 rc 0).

## 4. Frozen-пин `ROUTES_SHA256_F11` — не затронут

Срез не трогает `web/api/routes.py` (по контракту ревью — только
`services/telegram_send.py`, `services/direct_chat_service.py`, тесты,
evidence), поэтому переутверждение не требуется.

```text
git diff --numstat 54546ab5b HEAD -- web/api/routes.py   -> <пусто, 0 строк>
sha256(web/api/routes.py) = 677bef0bf37f60aff8649c72b35de05b8e217fc6fb50533bd9ee8b1258645719
size                      = 403267 B
ROUTES_SHA256_F11         = 677bef0b… (tests/test_round1025_f8_registry.py) — совпадает
```

Вторая копия пина в `tests/test_mca23_planned_vs_actual.py`
(`453e17f8…`) остаётся собственной устаревшей копией: она падает одинаково на
базе и кандидате (§6), не импортирует канон и не правилась.

**Производные артефакты — 0 diff** (`git diff --numstat 54546ab5b HEAD` пуст):
`services/param_catalog.py`, `services/pg_db.py`, `services/database.py`,
`plans/docs/param-registry-round1025.tsv`, `…/screen-map-round1025.md`,
`tests/fixtures/round1025/f8_baseline.json` (и весь `tests/fixtures/round1025/`).
`python tools/gen_param_registry_round1025.py --check` → **rc 0**
(`CHECK OK: реестр 659 == REGISTRY, карта полна, R17-чисто, TSV/map
идемпотентны`). Hash-константы `PG_DB_SHA256_B07`, `PARAM_CATALOG_SHA256_*`
не менялись; производные файлы не перегенерировались.

## 5. OpenAPI

`create_app(MagicMock()).openapi()`:

| | paths | operations |
|---|---|---|
| база `54546ab5b` | **221** | **261** |
| кандидат `de5f6cd0f` | **221** | **261** |

OpenAPI-набор **не изменился** (0 новых/удалённых endpoints): срез меняет
только тело исходящего chokepoint'а и тестовые стражи.

## 6. Тесты на финальном коде `de5f6cd0f`

Окружение: `C:\Code\Python\adminbot\.venv` (Python 3.12.0, pytest 9.1.1),
`ADMINBOT_SKIP_DOTENV=1`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`,
`PYTHONIOENCODING=utf-8`, cwd = worktree релиза. База сравнения — чистый по
tracked-файлам worktree `54546ab5b` (unit 2.58.253), тот же интерпретатор,
те же файлы **без** нового теста (36 против 37).

| Прогон | Кандидат `de5f6cd0f` | База `54546ab5b` | Совпадение FAILED |
|---|---|---|---|
| 37 файлов: новый тест + outgoing-guard + M1-C lock/invariant + chat/telemetry/log-ring + version pins | **6 failed, 1372 passed** (104.77 s) | 36 файлов: **6 failed, 1347 passed** (100.50 s) | **да: 6 == 6** |
| история «известного красного» (4 файла)* | **4 failed, 47 passed** (8.03 s) | **4 failed, 47 passed** (6.85 s) | **да: 4 == 4** |
| `tests/test_mod_acl_ux_01_s4_172_egress.py` отдельно | **22 passed** (8.63 s) | файла нет | n/a |
| `tests/test_outgoing_guard_round1022.py` отдельно | **27 passed, 1 failed** (4.61 s) | **24 passed, 1 failed** (3.71 s) | да (та же `meme_command`) |
| `node --check web/app.js` | **rc 0** | — | — |
| 4 JS version-пина (`node tests/js/round1025_hotfix{7,8,9,10}_…js`) | **4/4 rc 0** | — | — |
| `py_compile` 31 изменённый `.py` (срез + wave) | **31/31 rc 0** | — | — |
| `git diff --check 54546ab5b HEAD` | **rc 0** | — | — |

\* `test_prompt_field_audit.py`, `test_mod_acl_ux_01_m4_module_params.py`,
`test_status_section_ui_merge_round1019.py`, `test_mca23_planned_vs_actual.py` —
предсуществующий красный набор, прогонялся отдельно на обеих сторонах.

Разница прошедших `1372 − 1347 = +25` = 22 новых теста F01/egress-файла +
3 новых теста стража в `test_outgoing_guard_round1022.py`. Ни одного нового
падения кандидат не вносит. Все **10** падений (6 + 4) идентичны на базе
одними и теми же node id:

```text
tests/test_outgoing_guard_round1022.py::TestSendPointsCoverage::test_every_send_point_is_registered_or_allowlisted
tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff
tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools
tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged
tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline
tests/test_webapp_f9_round1025.py::TestInvariants::test_secrets_count_28
tests/test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface
tests/test_mod_acl_ux_01_m4_module_params.py::test_js_fixture_matches_live_contract
tests/test_status_section_ui_merge_round1019.py::TestStatusSectionMerge::test_mode_version_line_removed
tests/test_mca23_planned_vs_actual.py::TestResponseEndpoints::test_routes_pin_untouched
```

Первое падение — предсуществующая незарегистрированная send-точка
`handlers/meme_command.py` (вне write scope строки, backlog `SD172-R2-F02`),
остаётся и на базе; остальные девять — исторический красный набор 2.58.253.

Логи прогонов: `test-output/` рядом с этим файлом
(`candidate-37files.txt`, `base-36files.txt`,
`candidate-knownred-4files.txt`, `base-knownred-4files.txt`,
`js-pins-node.txt`, `derived-artifacts.txt`, `openapi.txt`, `git-facts.txt`).

## 7. Manifest dry-run

`tools/release_manifest.py --repo-root . --dry-run` на коде `de5f6cd0f`
(временный untracked seed `.deploy/release.json` с предыдущим деплоем
`54546ab5b / 2.58.253`; после прогона удалён, в коммит не попал):

```json
{
  "deployed_at": "2026-11-26T20:39:17.907967Z",
  "deployed_sha": "de5f6cd0fdb74f81a3a45236670d2f0300180fc0",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "54546ab5b201a5d8bd169bad613e730d371fc3b9",
  "previous_version": "2.58.253",
  "release_branch": "release/mod-acl-egress-2.58.254",
  "schema": 1,
  "version": "2.58.254"
}
```

`deployed_sha` = фактический `git rev-parse de5f6cd0f`; `version` читается
AST-разбором `config/settings.py` этого checkout. Evidence-коммит добавляет
только документы/логи (код не меняется) — DevOps обязан записать манифест на
проверенном checkout после деплоя. **DDL 0, миграции 0, новые флаги 0, новые
endpoints 0**, OpenAPI 221/261 без изменений, схема v48.

## 8. Откат

- Code-only, `git`-откат на `54546ab5b201a5d8bd169bad613e730d371fc3b9`
  (2.58.253), `tools/release_manifest.py --effect rollback`.
- DDL 0, миграций 0, новых флагов 0 → схема и данные совместимы в обе стороны;
  пользовательские настройки/секреты/история не затрагиваются (меняется только
  исходящий текст: при откате возвращается прежнее поведение без маски секретов
  в чате и без строгого стража — это и есть откат дефекта).

## 9. Что не проверялось (честно)

- Живая доставка в Telegram не проверялась: проверена граница
  `bot.send_message`/`edit_text`/`send_message`-payload (fake-bot) — фактический
  payload, который уходит в Bot API (slice evidence). LLM в тестах подменён
  stub'ом (`persona_short_reply`), states/readiness настоящие.
- Effective-state прода (версия, схема, identity, healthz, served blobs,
  disk keep=2) — DevOps после деплоя; production не затрагивался, SSH/деплой
  запрещены заданием.
- Полный ~23k-набор не прогонялся; покрытие — набор §6.

## 10. Гигиена

- Worktree `…-40924ee6` — активная линия релиза, зарегистрирован
  (`unit release-2.58.254`), сохраняется до деплоя/решения.
- Overlay-скрипты сборки (bump/reverse-proof/pins/openapi/evidence/manifest seed)
  и полные логи прогонов выполнялись из временного каталога
  `%TEMP%\opencode\rel254`; компактные `test-output/*` этого релиза скопированы
  в ветку, после чего временный каталог **удалён** (в репозитории только
  воспроизводимые команды и компактные результаты).
- `.deploy/release.json` (seed) удалён; tracked-дерево чистое.
- `review-r2.md` — артефакт Reviewer, скопирован байт-в-байт (sha256
  `71370327…a8fba`); он не входит в коммиты среза и добавлен в ветку релиза,
  чтобы решение об одобрении кандидата `443a1eb76` было в самой ветке
  (прецедент 2.58.253: `review-r1.md` в assembly-коммите).
