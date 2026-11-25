# Сборка 2.58.249 — UR-F (применимость/readonly параметров, честные режимы)

- **Роль:** Builder, локальная сборка. **Без deploy, merge в master, SSH и
  production.** Effective-state прода и post-deploy проверки — DevOps после
  выкладки; этот документ — вход для delta-ревью релизного кандидата.
- **База (production 2.58.248):** `b01138b556572e55802755960cf4437eb3ff3b06`.
- **Ветка:** `release/ur-f-2.58.249` от `b01138b55` в registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/unified-reply-41500c30aca7-b6d998ac`,
  epic `unified-reply`). Интеграция — линейные cherry-pick, **без merge-коммитов**.
- **Срез:** `UR-F`, ветка `feat/ur-f-params`, tip `55cd1b4b3c084d24119a6d0bb7a794c292047b2a`
  (предыдущий `90f4114f3`). Ревью: r1 → NEEDS_FIXES (`URF-R1-F1`), r2 →
  `APPROVED_FOR_RELEASE_PREPARATION`; строки `UR-21`, `UR-22`, `UR-29`,
  `UR-RES-07` — PASS.

```json
{
  "release": "2.58.249",
  "base": {"sha": "b01138b556572e55802755960cf4437eb3ff3b06", "version": "2.58.248"},
  "slice": {
    "id": "UR-F", "name": "params applicability/readonly + honest modes",
    "branch": "feat/ur-f-params",
    "base": "b01138b556572e55802755960cf4437eb3ff3b06",
    "source_tip": "55cd1b4b3c084d24119a6d0bb7a794c292047b2a",
    "previous_tip": "90f4114f3049487a477c61c2ce27628cb6a6f7d8",
    "product_commits": ["9d6809f3d", "55cd1b4b3"],
    "evidence_commits": ["9d6809f3d", "13334d4e5", "ee33f4206", "90f4114f3",
                         "55cd1b4b3"],
    "review": {
      "r1": "plans/features/unified-reply/evidence/ur-f-params-review-r1.md",
      "r1_sha256": "a7526c38eb4a0989cca66883b1449ca9fb4fa0d307e46f2010ffb47e48ffcfb8",
      "r1_verdict": "NEEDS_FIXES (URF-R1-F1: чип режима противоречил строке на двух карточках)",
      "r2": "plans/features/unified-reply/evidence/ur-f-params-review-r2.md",
      "r2_sha256": "238d60e00d9553f6f2630009edb03213b4c6ab948b6d7c1e98719311957107cb",
      "hash_reproduced": true,
      "verdict": "APPROVED_FOR_RELEASE_PREPARATION"
    },
    "per_row": {"UR-21": "PASS", "UR-22": "PASS", "UR-29": "PASS",
                "UR-RES-07": "PASS"}
  },
  "integration": "linear cherry-pick: slice (5 commits), version wave (1), derived registry sync + L-F11S-1 re-pin (1)",
  "commits_above_base": 7,
  "delta_vs_base": {"files": 68, "insertions": 1370, "deletions": 122}
}
```

sha256 воспроизведены с planning-checkout (`master`), потому что evidence-ревью
живут в плановой линии и не входят в код-базу 2.58.248.

## 1. Порядок интеграции

| # | интеграционный SHA | источник | тип |
|---|---|---|---|
| 1 | `12deb932f` | UR-F `9d6809f3d` | product (backend-ось применимости, `eff.readonly`, честные режимы) |
| 2 | `c094b727a` | UR-F `13334d4e5` | evidence (RED-снапшот помечен одноразовым) |
| 3 | `d5cfb7d40` | UR-F `ee33f4206` | evidence (формулировки readonly) |
| 4 | `faaab5b3b` | UR-F `90f4114f3` | evidence (UTF-8 восстановлен, 4→5 тестов) |
| 5 | `2789c4247` | UR-F `55cd1b4b3` | product (URF-R1-F1: чип режима из фактического статуса) |
| 6 | `0def456fc` | — | version wave 2.58.249 |
| 7 | `d0255693e` | — | производная синхронизация реестра + L-F11S-1 re-pin (§4) |

Cherry-pick прошли без конфликтов; ручных правок кода среза при сборке не
потребовалось. Порядок — ровно как в ветке среза (линейный).

## 2. Файлы среза: побайтовая идентичность

Срез затрагивает **34 файла** (8 кода/тестов + 26 evidence), `git diff
--name-status b01138b55..55cd1b4b3`. Проверка механическая (`git rev-parse
HEAD:<path>` против tip'а среза) на финальном кандидате:

| файл | blob (12) HEAD | blob (12) 55cd1b4b3 |
|---|---|---|
| `services/param_catalog.py` | `2ffce87a15d9` | `2ffce87a15d9` |
| `web/app.js` | `c1d1fa6cbe6f` | `c1d1fa6cbe6f` |
| `web/index.html` | `39e740eeef09` | `39e740eeef09` |
| `tests/js/ur_ui_settings_test.js` | `cbc243e7f7ef` | `cbc243e7f7ef` |
| `tests/js/unified_ui21_test.js` | `794df62bfcae` | `794df62bfcae` |
| `tests/test_cfg03_param_audit.py` | `015d3d1797e8` | `015d3d1797e8` |
| `tests/test_ur_ui_effective_config.py` | `07a4fc360d52` | `07a4fc360d52` |
| `tools/ui_urf_visual_e2e.py` | `a87b9fd8abaf` | `a87b9fd8abaf` |
| `plans/features/unified-reply/evidence/ur-f-params-2026-11-26.md` | `cb1521a3449b` | `cb1521a3449b` |
| `.../ur-f-params-2026-11-26/visual/**` (24 png + `urf-visual-report.json`, 25 файлов) | — | — |

Итог: **34/34 файла байт-в-байт равны blob'у среза**; `git diff --stat
55cd1b4b3..HEAD -- <8 файлов + evidence.md>` пуст, дерево среза равно tip'у
(`HEAD^{tree}` до version wave = `884da3631bf0cc6e1e631452af7f79569407dc0e` ==
`55cd1b4b3^{tree}`).

## 3. Version wave 2.58.249 (32 файла / 35 строк)

Байтовая замена только токена версии; BOM/переводы строк сохранены. Проверка:
обратная замена (`2.58.249 → 2.58.248`, плюс обратная подстановка головы
`APP_VERSION`-строки в `config/settings.py`) даёт **байт-в-байт blob HEAD**
для каждого из 32 файлов, признаки BOM и счётчики CRLF/LF не изменились —
**32/32 файлов reverse-byte-identical**, расхождений 0.

- `config/settings.py` — 1 строка: `APP_VERSION = "2.58.249"` + релизная
  заметка этого выпуска в той же строке; предыдущая запись стала
  `Prior (25.11.2026): 2.58.248 - ...` (BOM сохранён, 3665 CRLF / 3665 LF);
- `plans/docs/param-registry-round1025.meta.md` — 1 (`APP_VERSION`);
- 4 × `tests/js/*` — 4 (экранированный пин `2\.58\.NNN`);
- 24 py-пина — 25 (23 × 1 + `test_webapp_round1026_polygon.py` 2);
- `tools/ui_mod_acl_m4b2_status_e2e.py` 3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1.

Итог: **32 файла, 35 строк**, `git diff --shortstat` подтверждает
(`32 files changed, 35 insertions(+), 35 deletions(-)`), коммит `0def456fc`.
JS-пины `?v=` в `web/index.html` — шаблон `__APP_VERSION__` (не литерал),
поэтому отдельных правок не требуют; они проверены тестами пинов.

`services/param_catalog.py` в version wave **не входил** (байтовая
идентичность среза сохранена).

## 4. Найдено сборкой: производная синхронизация реестра (UR-21/22)

Сборка поймала дефект, которого не было в отчётах среза: `UR-21` выводит два
ключа из пользовательского редактирования (`hidden`), но производные артефакты
F8 и frozen-пин каталога не были пересчитаны. На кандидате без правки падали
**3 теста, зелёные на базе** `b01138b55`:

- `test_round1025_f8_registry::TestFrozenInvariants::test_param_catalog_unchanged`
  — `services/param_catalog.py изменился вне санкционированной дельты`
  (sha256 базы `c7cb2bdb…` → фактический `8e64374a…`);
- `TestGeneratorIdempotency::test_check_passes_on_committed` и
  `::test_check_subprocess_exit_zero` — `TSV расходится с каталогом`,
  `screen-map расходится с каталогом`.

Исправлено **производной** синхронизацией (коммит `d0255693e`, 4 файла,
+21/−7), без изменения кода и поведения среза:

- `plans/docs/param-registry-round1025.tsv` и `screen-map-round1025.md`
  переэмитированы штатным `tools/gen_param_registry_round1025.py` — ровно 2
  строки каждый: `limits.chat_context_fill_ratio` и
  `limits.chat_current_question_max_chars` → `hidden=true`, `нет API (hidden)`,
  подписи/причины из одобренного каталога;
- `plans/docs/param-registry-round1025.meta.md` — только `HEAD (short)`;
- `tests/test_round1025_f8_registry.py` — `PARAM_CATALOG_SHA256_FOLLOWUP`
  пересчитан на `8e64374a…` (L-F11S-1: осознанное переутверждение
  санкционированной дельты; коммент с составом дельты) и
  `assert len(hidden) == 17 → 19` + два ключа в `hidden_keys` (тот же
  санкционированный сдвиг видимости).

Счётчики каталога не менялись: **REGISTRY 659 / GROUPS 121 / TAB_RULES 23 /
Settings 477** — идентично базе (проверено импортом на обоих деревьях), новых
флагов/ParamSpec нет. `readonly`-ось (`_EFFECTIVE_READONLY`, 16 ключей) —
метаданные, не флаг.

**Честная граница роли:** пересчёт frozen-hash носит механический характер и
вытекает из уже одобренного каталога; «осознанное переутверждение» по
L-F11S-1 даёт независимое delta-ревью этого релизного кандидата, а не автор
сборки. Если ревью сочтёт дельту каталога неразрешённой — это блокер среза, и
коммит `d0255693e` откатывается отдельно.

## 5. Тесты на точном кандидате `d0255693e`

Прогон в этом worktree, интерпретатор `C:\Code\Python\adminbot\.venv`
(Python 3.12, pytest), `-p no:cacheprovider`. Единственный коммит после
код-кандидата — этот evidence-файл (код не меняется).

| набор | passed | failed |
|---|---|---|
| `tests/test_ur_ui_effective_config.py` | **36** | 0 |
| 7-файловый param/catalog: `test_param_catalog`, `test_cfg03_param_audit`, `test_ur_11_single_owner`, `test_ur_12_summary_watermark`, `test_ur_context_selection`, `test_ur_c_clock`, `test_ur_ui_effective_config` | **201** | 1 (pre-existing) |
| webapp/inspector/ur_e: `test_webapp_api`, `test_ur_f_inspector_step1`, `test_ur_e_speech` | **233** | 1 (pre-existing) |
| пины версии (24 py-файла, включая `test_round1025_f8_registry` 29/29) | **855** | 5 (pre-existing) |
| JS: `tests/js/ur_ui_settings_test.js` | `UR-F-UI-OK` | 0 |
| JS: `tests/js/unified_ui21_test.js` | `UNIFIED-UI21-OK` | 0 |
| JS-каталог: все `tests/js/*_test.js` (138 файлов) | **131** | **7** |
| структурное: `node --check` (`web/app.js`, `ur_ui_settings_test.js`, `unified_ui21_test.js`) | 3/3 rc 0 | 0 |
| структурное: `py_compile` всех 31 изменённых `.py` (base..HEAD) | 31/31 ok | 0 |
| структурное: `git diff --check` (worktree и диапазон base..HEAD) | rc 0 / rc 0 | 0 |

### 5.1 Падения: доказательство идентичности базе

База `b01138b55` прогнана в отдельном registered worktree
(`.../ur-f-2-58-249-base-b47afe996836-b622950a`, detached) тем же
интерпретатором.

| # | тест | на кандидате | на базе |
|---|---|---|---|
| 1 | `test_cfg03_param_audit::TestConsumerCoverage::test_visible_dead_knobs_are_exactly_documented` | FAILED | FAILED |
| 2 | `test_ur_f_inspector_step1::test_identical_quotes_credit_only_the_surviving_item` | FAILED (`FakeDB` без `.db`) | FAILED |
| 3 | `test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff` | FAILED | FAILED |
| 4 | `test_tool_coordinator_round1026::TestBounds::test_canon_twelve_tools` | FAILED | FAILED |
| 5 | `test_unified_image_request_round1026::TestToolDescriptionU21::test_canon_unchanged` | FAILED | FAILED |
| 6 | `test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` | FAILED | FAILED |
| 7 | `test_webapp_f9_round1025::TestInvariants::test_secrets_count_28` | FAILED | FAILED |

- Прогон на базе `[test_round1025_f8_registry, test_tool_coordinator_round1026,
  test_unified_image_request_round1026, test_webapp_f9_round1025,
  test_cfg03::test_visible_dead_knobs…, test_ur_f_inspector::test_identical_quotes…]`
  → **7 failed, 125 passed**, набор падений — ровно 7 из таблицы; все 29 тестов
  `test_round1025_f8_registry` на базе **зелёные** (это и был единственный
  кандидат-специфичный дефект, §4).
- JS-каталог на базе: **130 passed / 8 failed** — те же 7 идентификаторов плюс
  `ur_ui_settings_test.js` (RED на базе, закрыт срезом → на кандидате 131/7).
- Новых падений относительно базы на финальном кандидате **нет**; ни один пин
  не подгонялся, падения не маскировались.

Известный долг базы (`BACKLOG_ONLY`, не контракт релиза): устаревшие пин-каноны
`tool_coordinator`/`unified_image_request`, `FakeDB` в `ur_f_inspector_step1`,
счётчик секретов `webapp_f9` (34 против пина 32), 4 невидимых ключа в
`test_visible_dead_knobs_are_exactly_documented`.

## 6. Manifest dry-run

Прогон `python tools/release_manifest.py --dry-run` на чистом дереве
код-кандидата `d0255693e`. В worktree нет `.deploy/release.json`, поэтому для
`previous_*` использован локальный untracked seed с прод-идентичностью
`b01138b55 / 2.58.248` (удалён сразу после прогона; ни одно поле не выдумано):

```json
{
  "deployed_at": "2026-11-25T18:51:44.166560Z",
  "deployed_sha": "d0255693e4aed5c1f3f04e38938221d3bc893471",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "b01138b556572e55802755960cf4437eb3ff3b06",
  "previous_version": "2.58.248",
  "release_branch": "release/ur-f-2.58.249",
  "schema": 1,
  "version": "2.58.249"
}
```

Инструмент берёт `deployed_sha` из `git rev-parse HEAD` момента прогона. Этот
документ — единственный коммит после код-кандидата (меняет только `plans/`),
поэтому повторный dry-run на финальном tip'е ветки даёт те же поля с
`deployed_sha` = фактический HEAD; штатная запись манифеста — DevOps на
сервере, где `deployed_sha` = HEAD выложенного checkout.

Контракт выкладки: **DDL 0, миграций 0, новых флагов 0, новых store/endpoint/
планировщиков нет**; `migrations/`, `models/`, `services/pg_db.py`,
`services/database.py` не затронуты; `config/settings.py` изменён только
строкой версии; схема v48.

## 7. Откат

- **Только код**, `git`-откат на `b01138b556572e55802755960cf4437eb3ff3b06`
  (2.58.248), `tools/release_manifest.py --effect rollback`. DDL 0, миграций 0,
  новых флагов 0, формат данных не меняется.
- Промпты не затрагиваются ни срезом, ни волной версии (canon-файлы не
  изменены); сохранённые пользовательские правки промптов не страдают.
- Данные production не мигрируются, восстановление БД не требуется.

## 8. Что осталось непроверенным (честно)

- Effective-state прода (фактическая версия `/healthz`, схема, identity
  деплоя, диск) — DevOps после выкладки; здесь production не затрагивался.
- Визуальный контракт среза проверен в срезе (`URF-VISUAL-OK`, 1440/390,
  `console_errors=0`, артефакты в evidence среза); при сборке визуальный слой
  не менялся, повторный Playwright/Browser Use не требовался — изменились
  только токен версии и производные docs.
- Реальное поведение моделей на живых чатах — не инженерный критерий приёмки
  (`BOUNDED ACCEPTANCE`), проверяется при эксплуатации.
- Полный `pytest` по репозиторию не является практикой проекта; наборы выбраны
  по затронутым контурам, остаточные падения сведены к доказанным base-pre-existing.

## 9. Очистка

- Временный `.deploy/release.json` seed удалён сразу после dry-run
  (`git status --porcelain` пуст).
- Базовый worktree для доказательства pre-existing (`ur-f-2-58-249-base-…`)
  удалён после прогонов; вспомогательные скрипты замены/проверки — в
  `WorkspaceData/temp`, репозиторий не затрагивали.
- Новых файлов вне среза, version wave, производной синхронизации и этого
  документа нет. Deploy/merge в master/SSH не выполнялись.
