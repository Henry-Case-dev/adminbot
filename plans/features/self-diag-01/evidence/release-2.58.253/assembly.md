# Сборка 2.58.253 — SELF-DIAG-01 postdeploy AC-11/D6-12 (глобальный ACL текста промпта + типизированный uptime)

- **Роль:** Builder, локальная сборка релиза. **Деплоя, SSH, merge в master,
  push --force нет.** Deploy/effective-state — DevOps после отдельного handoff.
- **База (production 2.58.252):** `b5bb71c7a6e89bbf13de88b6f013725dcf633563`.
- **Ветка:** `release/selfdiag-ac11-2.58.253` от `b5bb71c7a`, registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/selfdiag-ac11-release-258253-a478b6c24b00-53d77aef`,
  unit `selfdiag-ac11-release-2.58.253`). Интеграция — линейный cherry-pick,
  **без merge-коммитов**.
- **Срез:** ветка `fix/selfdiag-ac11-uptime`, tip
  `8816dc1d11abe8dcd1971be9b65ff838b7acb10c` (один коммит от базы). Ревью:
  `plans/features/self-diag-01/evidence/ac11-uptime/review-r1.md`, sha256
  `c191e120ca32fe544326aedcb271d632d9723ddc5c888b9ce03a2a43eefbc95c`
  (пересчитан копией в этой ветке, совпал), вердикт
  `APPROVED_FOR_RELEASE_PREPARATION`.
- **Строки:** AC-11 (глобальный `/api/config` не отдаёт текст промпта роли без
  гранта) и D6-12 (`/api/status/self-diagnosis` — типизированный uptime вместо
  `null`). Non-prompt настройки и поверхность `/api/speech/*` не сужены.

```json
{
  "release": "2.58.253",
  "base": {"sha": "b5bb71c7a6e89bbf13de88b6f013725dcf633563", "version": "2.58.252"},
  "slice": {
    "branch": "fix/selfdiag-ac11-uptime",
    "source_tip": "8816dc1d11abe8dcd1971be9b65ff838b7acb10c",
    "source_tree": "5d97168c0f5a0005b6523bfbf4f18c47605c2994",
    "review": {"artifact": "plans/features/self-diag-01/evidence/ac11-uptime/review-r1.md",
               "sha256": "c191e120ca32fe544326aedcb271d632d9723ddc5c888b9ce03a2a43eefbc95c",
               "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}
  },
  "integration": "linear cherry-pick (1 slice commit) + version wave (1) + routes re-pin (1) + this evidence",
  "slice_commits": 1,
  "cherry_pick_commit": "b93cf9a83fc363b302f94f2ac2ceb4d2f442c96a",
  "pre_bump_head": "b93cf9a83fc363b302f94f2ac2ceb4d2f442c96a",
  "pre_bump_tree": "5d97168c0f5a0005b6523bfbf4f18c47605c2994",
  "bump_commit": "45b4305ccc604c90cd98cf938acf4912fc7c4092",
  "bump_tree": "0083c653796efc3ba9809f38c36eb7263fa9a69d",
  "routes_pin_commit": "10da98a31a50a15877112b071d92e69d23c2be32",
  "code_tip": "10da98a31a50a15877112b071d92e69d23c2be32",
  "code_tip_tree": "1defbf0e8a8e829f6dcdc6dd3a8c81a031be669c",
  "evidence_commit": "tip of release/selfdiag-ac11-2.58.253 (this file + review-r1.md)",
  "delta_vs_base_at_code_tip": {"files": 37, "insertions": 461, "deletions": 52}
}
```

`delta_vs_base_at_code_tip` = `git diff --shortstat b5bb71c7a 10da98a31`:
5 файлов среза + 32 файла version wave (пересечения нет); re-pin входит в
число 32 (файл уже в version wave). Других отличий нет.

## 1. Порядок интеграции

| # | SHA (новая ветка) | Источник `fix/selfdiag-ac11-uptime` | Тип |
|---|---|---|---|
| 1 | `b93cf9a83` | `8816dc1d1` | AC-11 + D6-12: `routes.py`, `prompt_access.py`, `status_service.py`, новый тест, evidence README |

Cherry-pick выполнен стандартным `git cherry-pick -x` без правок; авторство и
дата коммита сохранены. После cherry-pick `HEAD^{tree}` =
`8816dc1d1^{tree}` = `5d97168c0…`: дерево **байт-в-байт** равно дереву среза
(`git diff --name-only 8816dc1d1 b93cf9a83` пуст).

## 2. Byte identity среза (5 файлов)

| файл | blob@8816dc1d1 | blob@HEAD |
|---|---|---|
| web/api/routes.py | `83c300c18192…` | `83c300c18192…` |
| web/api/prompt_access.py | `60fd9aa6c123…` | `60fd9aa6c123…` |
| services/status_service.py | `a43730004f54…` | `a43730004f54…` |
| tests/test_selfdiag_ac11_config_uptime.py | `9e9c6fcc5cea…` | `9e9c6fcc5cea…` |
| plans/features/self-diag-01/evidence/ac11-uptime/README.md | `a2bcad88dbc5…` | `a2bcad88dbc5…` |

Итого: **5/5 blob'ов идентичны** срезу на финальном коде
(`git diff --name-only 8816dc1d1 10da98a31` содержит только 32 файла version
wave; ни один файл среза в список не входит).

## 3. Version wave 2.58.253 (32 файла / 35 строк)

Только версии; коммит `45b4305cc`. `git diff --shortstat b93cf9a83 45b4305cc`
→ **32 файла, 35 insertions, 35 deletions** — ровно та же волна, что 2.58.252
(`5f0939049`), с заменой `2.58.252 → 2.58.253` в тех же 35 строках:
`config/settings.py` — 1 (pin `APP_VERSION = "2.58.253"` + релизная заметка
2.58.253 в существующей цепочке `Prior …`); `plans/docs/param-registry-round1025.meta.md`
— 1; 4 `tests/js/*` — 4 (regex-пины `2\.58\.253`); 24 py-теста — 25
(23 × 1 + `test_webapp_round1026_polygon.py` 2); `tools/ui_mod_acl_m4b2_status_e2e.py`
3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1.

**Обратная замена — byte-identical 32/32.** Обратное применение ровно внесённой
дельты (пины `2.58.253 → 2.58.252`, удаление вставленного сегмента заметки
2.58.253 в `config/settings.py`) дало blob'ы, байт-в-байт равные `b5bb71c7a`
для всех 32 файлов (проверено на финальном tip; для `config/settings.py` —
реконструкция из базовой строки даёт текущие байты побайтово).
BOM/переводы строк сохранены: `config/settings.py` — BOM `EF BB BF`, 3665
CRLF / 0 bare-LF / 0 bare-CR (как на базе); по всем 32 файлам BOM и CRLF/LF
совпадают с базой. JS-пины `?v=` в `web/index.html` — шаблон
`__APP_VERSION__` (literal-пина нет, файл не менялся).

## 4. Производный артефакт: re-pin `ROUTES_SHA256_F11`

Срез по контракту ревью меняет тело `web/api/routes.py` (глобальная ветка
`get_config` + `_self_diag_payload`), поэтому frozen-пин переутверждён
осознанно по прецеденту `L-F11S-1`, вычислением из фактических байт (без
ручной правки значения).

```text
old: 606899ac097d3a882b13693860dbe1dad7ad09816dcdd31630eaa88b16700663   (2.58.252)
new: 677bef0bf37f60aff8649c72b35de05b8e217fc6fb50533bd9ee8b1258645719
     sha256(web/api/routes.py), size 403267 B, git blob 83c300c18192… (== blob среза)
```

Изменён **один коммит** `10da98a31` — только каноническая константа в
`tests/test_round1025_f8_registry.py` (+ комментарий с предыдущим пином).
Тесты, импортирующие константу (`test_mca17c_invariants_round1047.py`,
`test_asap7_cover_preview.py`, `test_mca10b_…`, `test_mca12_…`), не содержат
второго значения и не правились.

**Доказательство деривации и чувствительности:**

| Шаг | Результат |
|---|---|
| `ROUTES_SHA256_F11 == sha256(web/api/routes.py)` | **True** |
| Немутированный файл: оба пина | **2 passed** |
| Мутация: `routes.py + b"\n"` (sha256 `cc083802…f4e29`) | **2 failed** (оба теста) |
| Восстановление байт из памяти процесса | sha256 = `677bef0b…45719`, byte-identical = **True** |
| После восстановления | **2 passed** |

`tests/test_mca23_planned_vs_actual.py` содержит **собственную устаревшую**
копию пина (`453e17f8…`), не импортирует каноническую константу и падает
одинаково на базе и кандидате (§6) — это не каноническое место, не правился.

**Другие производные артефакты — 0 diff:** `services/param_catalog.py`,
`services/pg_db.py`, `services/database.py`, `models/`, `migrations/`,
`plans/docs/param-registry-round1025.tsv`, `screen-map-round1025.md`,
`widget-map-round1025.md`, `tests/fixtures/round1025/f8_baseline.json`,
`…/catalog_baseline.json` — `git diff --numstat b5bb71c7a HEAD` пуст.
`python tools/gen_param_registry_round1025.py --check` → **CHECK OK**
(реестр 659 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны).
Hash-константы `PG_DB_SHA256_B07`, `PARAM_CATALOG_SHA256_*` не менялись.

## 5. OpenAPI

`create_app(MagicMock()).openapi()`: **221 path / 261 operation — и на базе
`b5bb71c7a`, и на кандидате `10da98a31`** → 0 новых endpoints; route-set и
RBAC не менялись (re-pin только из-за тела обработчиков).

## 6. Тесты на финальном коде `10da98a31`

Окружение: `C:\Code\Python\adminbot\.venv` (Python 3.12, pytest), `-p
no:cacheprovider`, `ADMINBOT_SKIP_DOTENV=1`, cwd = worktree релиза. База для
сравнения — чистый по tracked-файлам worktree `b5bb71c7a`
(`…-f68d0448`), тот же интерпретатор и те же 49 файлов (без нового теста).

| Прогон | Кандидат `10da98a31` | База `b5bb71c7a` | Совпадение FAILED |
|---|---|---|---|
| 50 файлов: новый тест + M1-C lock/invariant/predicate + prompt/config/status/checkup/diagnostic + version-pin + regression | **9 failed, 1531 passed, 1 warning** (140.99 s) | 49 файлов: **9 failed, 1524 passed, 1 warning** (130.60 s) | **да: 9 == 9** |
| `tests/test_selfdiag_ac11_config_uptime.py` отдельно | **7 passed** (4.86 s) | файла нет | n/a |
| M1-C lock + invariant + predicate + новый тест | **131 passed** (15.31 s) | — | n/a |
| `tests/test_round1025_f8_registry.py` | **29 passed** | — | n/a |
| Пин-пара (`test_routes_py_byte_freeze_pin_intact` + `test_routes_file_unchanged`) | **2 passed** / мутация **2 failed** / восстановление **2 passed** | — | — |
| 4 JS-версионных пина (`node tests/js/round1025_hotfix{7,8,9,10}_…js`) | **4/4 OK** (rc 0) | — | — |
| `node --check web/app.js` + 4 js-пина | **5/5 rc 0** | — | — |
| `py_compile` 30 изменённых `.py` (срез + version wave) | **30/30 ok** | — | — |
| `git diff --check` | **rc 0** | — | — |

Разница прошедших ровно +7 = новый файл (7 тестов). Списки падений идентичны:

```text
tests/test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface
tests/test_mod_acl_ux_01_m4_module_params.py::test_js_fixture_matches_live_contract
tests/test_status_section_ui_merge_round1019.py::TestStatusSectionMerge::test_mode_version_line_removed
tests/test_mca23_planned_vs_actual.py::TestResponseEndpoints::test_routes_pin_untouched
tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff
tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools
tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged
tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline
tests/test_webapp_f9_round1025.py::TestInvariants::test_secrets_count_28
```

Все девять воспроизводятся на базе теми же node id — ни одного нового падения
кандидат не вносит.

## 7. Manifest dry-run

`tools/release_manifest.py --repo-root . --dry-run` на коде `10da98a31`
(временный untracked seed `.deploy/release.json` с предыдущим деплоем
`b5bb71c7a / 2.58.252`; после прогона удалён, в коммит не попал):

```json
{
  "deployed_at": "2026-11-26T10:59:12.413221Z",
  "deployed_sha": "10da98a31a50a15877112b071d92e69d23c2be32",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "b5bb71c7a6e89bbf13de88b6f013725dcf633563",
  "previous_version": "2.58.252",
  "release_branch": "release/selfdiag-ac11-2.58.253",
  "schema": 1,
  "version": "2.58.253"
}
```

`deployed_sha` = фактический `git rev-parse 10da98a31`. Evidence-коммит
добавляет только этот документ и сохранённый review-артефакт (код не
меняется); повторный dry-run на итоговом tip даёт тот же манифест с
`deployed_sha` = фактическому HEAD и теми же `previous_sha/previous_version` —
DevOps обязан записать манифест на проверенном checkout после деплоя.
DDL 0, миграции 0, новые флаги 0, новые endpoints 0; `config/settings.py` —
только строка версии; схема v48.

## 8. Откат

- Code-only, `git`-откат на `b5bb71c7a6e89bbf13de88b6f013725dcf633563`
  (2.58.252), `tools/release_manifest.py --effect rollback`.
- DDL 0, миграций 0, новых флагов 0 → схема и данные совместимы в обе стороны;
  пользовательские данные/настройки/секреты не затрагиваются; значения
  промптов не переписывались (ACL — только чтение).

## 9. Что не проверялось (честно)

- Живой Telegram-WebView и реальные `chat_admins` — стенд не поднимался
  (деплой и SSH запрещены заданием); проверка RBAC — существующими
  TestClient/HMAC-тестами среза.
- Effective-state прода (версия, схема, identity, healthz) — DevOps после
  деплоя; production не затрагивался.
- Полный 23k-набор не прогонялся; покрытие — набор §6.

## 10. Гигиена

- Worktree `…-a478b6c24b00-53d77aef` — активная линия релиза, зарегистрирован
  (`unit selfdiag-ac11-release-2.58.253`), сохраняется до деплоя/решения.
- Overlay-скрипты сборки (bump/reversal/pin-proof/openapi/manifest seed) и
  логи прогонов — во временном каталоге `%TEMP%\opencode\release-258253`;
  в репозиторий не копировались. Удалить после deploy/binding-решения.
- `.deploy/release.json` (seed) удалён; в коммитах только срез, version wave,
  re-pin, review-артефакт и этот документ.
