# Сборка 2.58.250 — UR-G/UR-B (инициативная трасса доставки + acceptance-доказательства)

- **Роль:** Builder, локальная сборка. **Без deploy, merge в master, SSH и
  production.** Effective-state прода и post-deploy проверки — DevOps после
  выкладки; этот документ — вход для delta-ревью релизного кандидата.
- **База (production 2.58.249):** `af8de2ac6e59f4c0b899c0c839f02258a9e02236`.
- **Ветка:** `release/ur-gb-2.58.250` от `af8de2ac6` в registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/unified-reply-41500c30aca7-4b645e38`,
  epic `unified-reply`). Интеграция — линейные cherry-pick, **без merge-коммитов**.
- **Срез:** `UR-G/UR-B`, ветка `feat/ur-gb-rows`, tip
  `8929f04cbc91b02ba1b2b9557b24f92a5af5d304` (предыдущий `2837a719f`,
  функциональная часть `6d10d35de` + корректива F1 в `8929f04cb`).
  Ревью: r1 → NEEDS_FIXES (`URGB-R1-F1`), r2 →
  `APPROVED_FOR_RELEASE_PREPARATION`; строки `UR-RES-01`, `UR-30.2`,
  `UR-07.3`, `UR-17.7`, `UR-17.8` — PASS.
- **Сессия сборки:** `ses_deb67df3dffe0mJeDC3a7D0yfA`.

```json
{
  "release": "2.58.250",
  "base": {"sha": "af8de2ac6e59f4c0b899c0c839f02258a9e02236", "version": "2.58.249"},
  "slice": {
    "id": "UR-G/UR-B", "name": "initiative turn-trace delivery parity + acceptance proofs",
    "branch": "feat/ur-gb-rows",
    "base": "af8de2ac6e59f4c0b899c0c839f02258a9e02236",
    "source_tip": "8929f04cbc91b02ba1b2b9557b24f92a5af5d304",
    "previous_tip": "2837a719f0456085cc4d08538fd2f0638f4822a0",
    "product_commits": ["6d10d35de", "8929f04cb"],
    "evidence_commits": ["6d10d35de", "1599c77d0", "2837a719f", "8929f04cb"],
    "review": {
      "r1": "plans/features/unified-reply/evidence/ur-gb-rows-review-r1.md",
      "r1_sha256": "9da4c9e81dcb023e60f9acf46f84026e3307b755a097664495084fe6fe84b792",
      "r1_verdict": "NEEDS_FIXES (URGB-R1-F1: стадия доставки инициативы не записывалась на всех терминальных путях)",
      "r2": "plans/features/unified-reply/evidence/ur-gb-rows-review-r2.md",
      "r2_sha256": "6f7114e84cd418b6aa2461357c960b7867eb4566762a998237328d703560713c",
      "hash_reproduced": true,
      "verdict": "APPROVED_FOR_RELEASE_PREPARATION"
    },
    "per_row": {"UR-RES-01": "PASS", "UR-30.2": "PASS", "UR-07.3": "PASS",
                "UR-17.7": "PASS", "UR-17.8": "PASS"}
  },
  "integration": "linear cherry-pick: slice (4 commits), version wave (1)",
  "commits_above_base": 5,
  "delta_vs_base": {"files": 39, "insertions": 1771, "deletions": 39}
}
```

sha256 воспроизведены с planning-checkout (`master`): evidence-ревью r1/r2 живут
в плановой линии, r2 не входит в код-базу; r2-файл в срезе отсутствует и здесь
не создавался.

## 1. Порядок интеграции

| # | интеграционный SHA | источник | тип |
|---|---|---|---|
| 1 | `b9caf9340` | UR-G/UR-B `6d10d35de` | product + tests + evidence (trajectory parity UR-RES-01, acceptance proofs) |
| 2 | `f04acd6bc` | UR-G/UR-B `1599c77d0` | evidence (фиксация кандидата `6d10d35de`) |
| 3 | `b63b6adf2` | UR-G/UR-B `2837a719f` | evidence (cleanup record, retention worktree) |
| 4 | `4638fdc4f` | UR-G/UR-B `8929f04cb` | product + tests + evidence (URGB-R1-F1: стадия доставки на всех терминальных путях) |
| 5 | `86dc25755` | — | version wave 2.58.250 |

Cherry-pick прошли без конфликтов; ручных правок кода среза при сборке не
потребовалось. Порядок — ровно как в ветке среза (линейный). Ветка среза также
несёт уже отслеживаемые evidence-файлы (`ur-gb-rows-2026-11-26.md`,
`ur-gb-retention-2026-11-26.json`, `ur-gb-rows-review-r1.md`) — они взяты как
часть reviewed tip; новых evidence-файлов сверх среза не создавалось.

## 2. Файлы среза: побайтовая идентичность

Срез затрагивает **7 файлов** (`git diff --name-status af8de2ac6..8929f04cb`:
2 product, 2 новых теста, 3 evidence). Проверка механическая (`git rev-parse`
blob'ов на кандидате до version wave против tip'а среза):

| файл | blob (12) HEAD | blob (12) 8929f04cb |
|---|---|---|
| `services/direct_chat_service.py` | `70fe3320e1fd` | `70fe3320e1fd` |
| `services/turn_trace.py` | `21738e3120d4` | `21738e3120d4` |
| `tests/test_ur_acceptance_trace.py` | `82648e08847c` | `82648e08847c` |
| `tests/test_ur_search_first.py` | `7355d54812ab` | `7355d54812ab` |
| `plans/features/unified-reply/evidence/ur-gb-rows-2026-11-26.md` | `65bbffcffa64` | `65bbffcffa64` |
| `plans/features/unified-reply/evidence/ur-gb-retention-2026-11-26.json` | `29e4ffe9020e` | `29e4ffe9020e` |
| `plans/features/unified-reply/evidence/ur-gb-rows-review-r1.md` | `f9e6cdde272e` | `f9e6cdde272e` |

Итог: **7/7 файлов байт-в-байт равны blob'у среза**; `git diff --stat
8929f04cb..<пре-bump HEAD>` пуст, дерево до version wave равно tip'у среза
(`4638fdc4f^{tree}` = `8929f04cb^{tree}` = `44771697ce5181fc3c6f132dd62e83e2c0c00b5f`).

## 3. Version wave 2.58.250 (32 файла / 35 строк)

Байтовая замена только токена версии; BOM/переводы строк сохранены. Проверка
обратной заменой (`2.58.250 → 2.58.249` по всем 32 файлам, для
`config/settings.py` — обратная подстановка головы `APP_VERSION`-строки) даёт
**byte-в-byte blob pre-bump HEAD** для каждого файла: **32/32 файлов
reverse-byte-identical**, расхождений 0.

- `config/settings.py` — 1 строка: `APP_VERSION = "2.58.250"` + релизная заметка
  этого выпуска в той же строке; запись 2.58.249 стала `Prior (26.11.2026):
  2.58.249 - ...` (BOM сохранён, 3665 CRLF / 3665 LF — как до bump);
- `plans/docs/param-registry-round1025.meta.md` — 1 (`APP_VERSION`);
- 4 × `tests/js/*` — 4 (экранированный пин `2\.58\.NNN`);
- 24 py-файла пинов — 25 (23 × 1 + `test_webapp_round1026_polygon.py` 2);
- `tools/ui_mod_acl_m4b2_status_e2e.py` 3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1.

Итог: **32 файла, 35 строк**, `git diff --shortstat` подтверждает
(`32 files changed, 35 insertions(+), 35 deletions(-)`), коммит `86dc25755`.
JS-пины `?v=` в `web/index.html` — шаблон `__APP_VERSION__` (не литерал),
отдельных правок не требуют; проверены тестами пинов.

Исторические комментарии `release 2.58.249` в `tests/test_round1025_f8_registry.py`
(2 строки про UR-F-дельту) **не bump'ились** — они описывают уже выпущенный
релиз 2.58.249; поэтому волна ровно 35 строк, как и 2.58.249.

`services/param_catalog.py` в version wave **не входил**.

## 4. Производные артефакты: переэмиссия не требуется

- Срез **не трогает** `services/param_catalog.py`: blob
  `2ffce87a15d9` и на базе `af8de2ac6`, и на HEAD; `git diff --stat
  af8de2ac6 HEAD -- services/param_catalog.py` и производные
  (`param-registry-round1025.tsv`, `screen-map-round1025.md`,
  `param-registry-round1025.meta.md`) — пусто (кроме version-строки meta).
- `python tools/gen_param_registry_round1025.py --check` → **CHECK OK**:
  реестр 659 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.
- Счётчики каталога: REGISTRY 659 / GROUPS 121 / TAB_RULES 23, Settings 477 —
  идентично базе; новых флагов/ParamSpec нет; `config/settings.py` изменён
  только строкой версии.

Переэмиссия F8 и пересчёт frozen-пинов не потребовались; hand-edit производных
не выполнялся.

## 5. Тесты на точном кандидате `86dc25755`

Прогон в этом worktree, интерпретатор `C:\Code\Python\adminbot\.venv`
(Python 3.12, pytest), `-p no:cacheprovider`. Единственный коммит после
код-кандидата — этот evidence-файл (код не меняется).

| набор | passed | failed |
|---|---|---|
| `tests/test_ur_acceptance_trace.py` + `tests/test_ur_search_first.py` | **14** (6 + 8) | 0 |
| соседние наборы r2: `asap8_f6_initiative`, `ur_d_writer`, `ur_e_speech`, `ur_turn_engine`, `ur26_init_fc_payloads`, `ur_b_live_wiring`, `mod_acl_ux_01_m21_gates`, `nostalgia_proactive_recall` | **135** | 0 |
| `direct_chat` + `ur_ui_effective_config` + `rlr_observability` | **203** | 0 |
| `evol_social_frame` + `evol_evidence_routing` + `soul1_style_payload` | **143** | 0 |
| пины версии: 24 py-файла волны (включая `test_round1025_f8_registry`) | **855** | **5** (pre-existing) |
| JS: 4 изменённых `tests/js/round1025_hotfix*_test.js` | 4/4 `*-OK` | 0 |
| структурное: `node --check` (`web/app.js`, 2 JS из волны) | 3/3 rc 0 | 0 |
| структурное: `py_compile` всех 31 изменённых `.py` (base..HEAD) | 31/31 ok | 0 |
| структурное: `git diff --check` (worktree и диапазон base..HEAD) | rc 0 / rc 0 | 0 |
| структурное: `tools/gen_param_registry_round1025.py --check` | CHECK OK | 0 |

### 5.1 Падения: доказательство идентичности базе

База `af8de2ac6` прогнана в отдельном registered worktree
(`.../unified-reply-41500c30aca7-e55b377a`, detached) тем же интерпретатором;
списки `FAILED` сравнены построчно (`Compare-Object`, 0 различий).

| набор | на кандидате `86dc25755` | на базе `af8de2ac6` |
|---|---|---|
| `asap8_initreply_binding` + `initiative_coordination` + `mca09_intents_block_e_round1040` + `initiative_delivery_telemetry` | **25 failed / 78 passed** | **25 failed / 78 passed**, тот же список |
| `nostalgia_worker` + `asap5_integration_w3` | **20 failed / 85 passed** | **20 failed / 85 passed**, тот же список |
| 24 pin-файла версии | **5 failed / 855 passed** | **5 failed / 855 passed**, тот же список |

Пять падений пинов (идентичны базе): `test_tool_coordinator_round1026::
TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`,
`test_unified_image_request_round1026::{TestToolDescriptionU21::
test_canon_unchanged,TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline}`,
`test_webapp_f9_round1025::TestInvariants::test_secrets_count_28`.
Новых падений относительно базы нет; ни один пин не подгонялся.

Известный долг базы (`BACKLOG_ONLY`, не контракт релиза): устаревшие
пин-каноны `tool_coordinator`/`unified_image_request`, счётчик секретов
`webapp_f9`, падения `initiative_*`/`nostalgia_worker`/`asap5_integration_w3`
(те же 45 идентификаторов на базе и кандидате).

## 6. Manifest dry-run

Прогон `python tools/release_manifest.py --dry-run` на чистом дереве
код-кандидата `86dc25755`. В worktree нет `.deploy/release.json`, поэтому для
`previous_*` использован локальный untracked seed с прод-идентичностью
`af8de2ac6 / 2.58.249` (удалён сразу после прогона; ни одно поле не выдумано):

```json
{
  "deployed_at": "2026-11-25T21:40:37.576436Z",
  "deployed_sha": "86dc257558bdd956476c1d54efd82a556d9d1add",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "af8de2ac6e59f4c0b899c0c839f02258a9e02236",
  "previous_version": "2.58.249",
  "release_branch": "release/ur-gb-2.58.250",
  "schema": 1,
  "version": "2.58.250"
}
```

Инструмент берёт `deployed_sha` из `git rev-parse HEAD` момента прогона. Этот
документ — единственный коммит после код-кандидата (меняет только `plans/`),
поэтому повторный dry-run на финальном tip'е ветки даёт те же поля с
`deployed_sha` = фактический HEAD; подтверждающий прогон выполнен после
evidence-коммита и приведён в handoff сборки. Штатная запись манифеста —
DevOps на сервере, где `deployed_sha` = HEAD выложенного checkout.

Контракт выкладки: **DDL 0, миграций 0, новых флагов 0, новых store/endpoint/
планировщиков нет**; `migrations/`, `models/`, `services/pg_db.py`,
`services/database.py` не затронуты (0 файлов в diff base..HEAD);
`config/settings.py` изменён только строкой версии; схема v48.

## 7. Откат

- **Только код**, `git`-откат на `af8de2ac6e59f4c0b899c0c839f02258a9e02236`
  (2.58.249), `tools/release_manifest.py --effect rollback`. DDL 0, миграций 0,
  новых флагов 0, формат данных не меняется.
- Промпты не затрагиваются ни срезом, ни волной версии (canon-файлы не
  изменены); сохранённые пользовательские правки промптов не страдают.
- Данные production не мигрируются, восстановление БД не требуется.

## 8. Что осталось непроверенным (честно)

- Effective-state прода (фактическая версия `/healthz`, схема, identity
  деплоя, диск) — DevOps после выкладки; здесь production не затрагивался.
- Визуальный контракт среза: срез меняет сервисный слой и trace, не UI;
  визуальный слой и `web/*` не изменены, поэтому повторный Playwright/Browser
  Use не требовался (в срезе визуального evidence нет и не заявлялось).
- Реальное поведение моделей на живых чатах — не инженерный критерий приёмки
  (`BOUNDED ACCEPTANCE`), проверяется при эксплуатации.

## 9. Очистка

- Временный `.deploy/release.json` seed удалён сразу после dry-run; каталог
  `.deploy/` удалён (`git status --porcelain` пуст).
- Базовый worktree для доказательства pre-existing
  (`.../unified-reply-41500c30aca7-e55b377a`) удалён после прогонов.
- Вспомогательные скрипты bump/verify — в `%TEMP%\opencode`, репозиторий не
  затрагивали.
- Новых файлов вне среза, version wave и этого документа нет. Deploy/merge в
  master/SSH не выполнялись.
