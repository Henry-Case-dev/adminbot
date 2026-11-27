# Release 2.58.260 — F-STALL-01 (loop-lag watchdog) + MOD-ACL card fix (два reviewed-кандидата одним релизом)

- **Дата сборки:** 2026-11-28
- **Роль:** Builder (сборка релиза, **без деплоя**)
- **Основание:** два независимо одобренных кандидата; файлы не пересекаются.
  - F-STALL-01 — review r1 **APPROVED_FOR_RELEASE_PREPARATION** (`a5c172e5…`), `plans/features/llm-vision-scheduler-p0/evidence/loop-lag-watchdog-2026-11-28/review-r1.md`.
  - MOD-ACL corrective — review r4 **APPROVED_FOR_RELEASE_PREPARATION** (`5663d2ed…`), `plans/features/mod-acl-ux-01/evidence/corrective-2026-11-27/review-r4/review-r4.md`.
- **База (deployed):** `1defb4e05fc3ed5cd1566b46af4eac0abd73a814` = **2.58.259**
- **Ветка:** `release/2.58.260`
- **Tip релиза (продуктовый):** `e967d1d0831c2a72af001d1a43a95a46d7ea9c36`
- **Tree:** `842d302de6b69af6d6049819858157251e121804`
- **Статус:** ASSEMBLED, не деплоился. Деплой — DevOps/Orchestrator.

## 1. Кандидаты

| # | Срез | Кандидат (reviewed) | Ветка | Контракт | Ревью |
|---|---|---|---|---|---|
| 1 | F-STALL-01 loop-lag watchdog | `79f251587874d3f9a98cc6e9ad59921a8c73279b` (code) + `24e10ec559bd731a43ae8bad794c8f42c126a66e` (evidence) | `feat/loop-lag-watchdog` | `loop-lag-watchdog-2026-11-28/index.md` | r1 APPROVED_FOR_RELEASE_PREPARATION |
| 2 | MOD-ACL-UX-01 corrective (card fix) | `d51b1afc588a389bfb0812c5fe745cb0339a1957` (+ цепь `13fc717c7`, `5be35bcf5`, `9c327dab2`) | `fix/mod-acl-corrective-2.58.258` | `corrective-2026-11-27/review-r4/review-r4.md` | r4 APPROVED_FOR_RELEASE_PREPARATION |

История ветки релиза (все переносы — `cherry-pick -x`, **ноль конфликтов**):

```
e967d1d08 chore(release): 2.58.260 - bump APP_VERSION and version pins
99dca746c fix(mod-acl): r3 — card back to the 132-164 contract   [cherry-pick -x]
3fb790d64 fix(mod-acl): r2 — scope-locked journal total
36483d6af fix(mod-acl): F1/F2/F3 review findings
53bf8d417 fix(mod-acl): D1/D2/D4/D5 acceptance blockers
11df48df1 docs(evidence): F-STALL-01 loop-lag watchdog verification [cherry-pick -x]
b1ff5acb0 feat(observability): bounded loop-lag watchdog (F-STALL-01) [cherry-pick -x]
1defb4e05 chore(release): 2.58.259 combined assembly evidence     ← deployed base
```

Почему конфликтов не было (проверено до переноса): F-STALL-01 отведён от `886d11073`
(2.58.258) и трогает только `bot.py`/`services/`/`tests/`; MOD-ACL corrective отведён от
`9516c9125` (2.58.257). Все файлы, которые они правят, **байт-идентичны этим точкам в базе
`1defb4e05`** (`git diff 9516c9125..1defb4e05` по web/app.js, web/index.html,
web/static/app.css, tools/ui_mod_acl_m4_catalog_e2e.py = пусто).

## 2. Байтовая идентичность reviewed-кода (доказано)

`raw/identity.txt`, `BYTE_IDENTICAL_ALL=True`. Сравнение — по git-blob (канонические байты).

| Срез | Файл | release tip blob | candidate blob | равно |
|---|---|---|---|---|
| F-STALL-01 | `services/loop_lag_watchdog.py` | `7a4a53f77d…` | `7a4a53f77d…` | ✅ |
| F-STALL-01 | `bot.py` | `e8f1d13efa…` | `e8f1d13efa…` | ✅ |
| F-STALL-01 | `tests/test_loop_lag_watchdog.py` | `29b801219f…` | `29b801219f…` | ✅ |
| MOD-ACL | `web/static/app.css` | `50ef54f3f4…` | `50ef54f3f4…` | ✅ |
| MOD-ACL | `tests/test_mod_acl_ux_m5c_corrective_e2e.py` | `2c8309d4c7…` | `2c8309d4c7…` | ✅ |
| MOD-ACL | `tools/ui_mod_acl_m4_catalog_e2e.py` | `4fc9fe0e40…` | `4fc9fe0e40…` | ✅ |

Остальные файлы MOD-ACL-среза (информационно, тоже байт-идентичны `d51b1afc5`):
`web/app.js` `27c8b172ab`, `web/index.html` `6e3afd9220`,
`tests/js/mod_acl_ux_m5c_corrective_test.js` `4c0dd90a21`,
`tests/js/mod_acl_ux_m4_catalog_test.js` `c21210ea8f`,
`tests/js/mod_acl_ux_m4a_w2a_tabs_freshness_test.js` `875310d847`,
`tests/js/mod_acl_ux_m4a_w2b_history_test.js` `c08a47f68d`,
`tests/js/round1025_f4_module_store_test.js` `34c035c8c2`.

**Восстановленный tool:** `tools/ui_mod_acl_m4_catalog_e2e.py` = `4fc9fe0e40…` = blob
форк-точки `9516c9125` = blob базы `1defb4e05` → правок в нём нет, он **не входит** в дельту
релиза (r3 вернул файл к контракту приёмки, review r4 §1).

## 3. Состав релиза от базы (42 файла)

`raw/product-delta.txt`:

| Часть | Файлов | Состав |
|---|---|---|
| F-STALL-01 продукт + тест | 3 | `bot.py` (+17/−1), `services/loop_lag_watchdog.py` (новый, 345), `tests/test_loop_lag_watchdog.py` (новый, 184) |
| F-STALL-01 evidence | 1 | `llm-vision-scheduler-p0/evidence/loop-lag-watchdog-2026-11-28/index.md` (перенесён cherry-pick'ом `24e10ec5`) |
| **MOD-ACL corrective** | **9** | `web/static/app.css`, `web/app.js`, `web/index.html`, `tests/test_mod_acl_ux_m5c_corrective_e2e.py` (новый, 331), `tests/js/mod_acl_ux_m5c_corrective_test.js` (новый, 384), 4 обновлённых JS-набора |
| Bump 2.58.260 | 29 | `config/settings.py`, `param-registry-round1025.meta.md`, 25 test-пинов, 2 tools |

`tools/ui_mod_acl_m4_catalog_e2e.py` в дельту не попал — он байт-идентичен базе (§2).
Итого `1defb4e05..e967d1d08` = **42 файла**, DDL 0.

## 4. Bump — version-only, набор не расширился

```
raw/bump-verify.txt
bump_commit=e967d1d0831c2a72af001d1a43a95a46d7ea9c36  parent=99dca746c
files=29  occurrences=34
non_version_changed_lines=0
crlf_files=1  lf_files=28
APP_VERSION = "2.58.260"
```

- Набор пинов **не расширился**: те же 29 файлов / 34 вхождения, что и в bump 2.58.259
  (`config/settings.py` ×1, `param-registry-round1025.meta.md` ×1,
  `test_q07_field_stats.py` ×3, `test_webapp_round1026_polygon.py` ×2,
  `ui_mod_acl_m4b2_status_e2e.py` ×3, остальные 24 файла ×1).
- Замена **побайтовая** (только литерал версии): 0 изменённых строк, кроме версии.
- `config/settings.py` — CRLF 3665 / bare LF 0 (как в 2.58.259); остальные 28 файлов — LF,
  line endings не затронуты (замена 9 байт без переводов строк).

## 5. Routes-пин — re-pin не нужен

```
raw/routes-pin.txt
routes_sha256_head = routes_sha256_base_1defb4e05 = 6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
ROUTES_SHA256_F11 = 6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
pin_matches_head = True   decision = no re-pin
```

`web/api/routes.py` ни одним срезом и ни bump'ом не менялся; пин в
`tests/test_round1025_f8_registry.py` остался тем же и зелёный
(`TestFrozenInvariants::test_routes_file_unchanged` — в наборе «пины», 864 passed).

## 6. DDL Δ = 0

```
raw/ddl-check.txt
changed files total: 42
changed DDL/schema files: []
services/database.py or migrations/ changed: False
{"ddl_delta": 0}
```

→ миграций при деплое нет, **rollback code-only** (схема/DDL не участвуют).

## 7. Прогоны

| Набор | Результат | Raw |
|---|---|---|
| F-STALL-01 новый модуль | **7 passed** | `tests-loop-lag.txt` |
| MOD-ACL e2e (контракт 132–164, 44px) | **5 passed** | `tests-modacl-e2e.txt` |
| MOD-ACL unit (m5c corrective) | **54 checks OK** | `js-m5c-overlay-unit.txt` |
| MOD-ACL catalog js | **207 проверок OK** | `js-m4-catalog.txt` |
| MOD-ACL w2a tabs js | **142 проверки OK** | `js-w2a-tabs.txt` |
| MOD-ACL module store js | **OK** | `js-module-store.txt` |
| MOD-ACL m5b + f5 | **30 passed** | `tests-m5b-f5.txt` |
| MOD-ACL m4 (3 файла) | **18 passed, 1 предсуществующий fail** | `tests-m4.txt` |
| Пины/реестр (25 файлов) | **864 passed, 6 предсуществующих fail** | `tests-pins.txt` |
| F8-реестр `--check` | **OK 659 == REGISTRY** | `f8-check.txt` |
| Стартовые smoke (10 файлов) | **81 passed** | `tests-startup-smoke.txt` |
| `test_round106_ia_smoke` | **42 passed, 3 предсуществующих fail** | `tests-round106-tip.txt` |

### 7.1 Предсуществующие red-ы — 10 node id, все воспроизведены на базе `1defb4e05`

База: `raw/tests-pins-base-red.txt`, `tests-round106-base.txt`, `tests-m4-base.txt`
(отдельный detached-worktree на `1defb4e05`, те же команды).

**Пины (6)** — `tests-pins-base-red.txt`:
`test_mca17c_invariants_round1047.py::test_no_ddl_catalog_ks_tools_delta`,
`test_tool_coordinator_round1026.py::TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`,
`test_unified_image_request_round1026.py::{TestToolDescriptionU21::test_canon_unchanged,TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline}`,
`test_webapp_f9_round1025.py::TestInvariants::test_secrets_count_28`.

**MOD-ACL m4 (1)** — `tests-m4-base.txt`:
`test_mod_acl_ux_01_m4_module_params.py::test_js_fixture_matches_live_contract`.

**IA-smoke (3)** — `tests-round106-base.txt`:
`test_round106_ia_smoke.py::TestRuntimeGates::test_youtube_gate_only_summary`,
`test_round106_ia_smoke.py::TestModulesAndAi::test_modules_exactly_11`,
`test_round106_ia_smoke.py::TestA6A7A9::test_access_windows`.

На tip те же 10 node id падают идентично (строки/ассерты совпадают); ни один red не связан
с обоими срезами. Проверки высоты карточки в tool-e2e на кандидате зелёные (review r4 §2).

## 8. Manifest dry-run

Снят на продуктовом tip `e967d1d08` (чистое дерево, `dirty_tracked=false`), прецедент 2.58.259.

```
raw/manifest-deploy.json
{
  "deployed_sha": "e967d1d0831c2a72af001d1a43a95a46d7ea9c36",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "bca5563be764dd3999b0cced9011e1e945bd9c0f",
  "previous_version": "2.58.259",
  "release_branch": "release/2.58.260",
  "schema": 1,
  "version": "2.58.260"
}
```

Затравка `.deploy/release.json` = фактический манифест прошедшего деплоя 2.58.259
(`raw/manifest-deploy.json` предыдущего релиза, `deployed_sha=bca5563be`).
Вариант с затравкой `deployed_sha=1defb4e05` (объявленная база/Orchestrator) —
`raw/manifest-deploy-previous-1defb4e05.json`, отличие только в `previous_sha`
(`1defb4e05…`), `previous_version` тот же `2.58.259`. Боевой манифест DevOps пишет по
фактическому HEAD прода.

`raw/manifest-rollback.json` — то же с `effect=rollback`, `previous_*` = 2.58.259.
**Rollback = code-only** (DDL Δ=0), возврат на выложенную `1defb4e05`/`bca5563be` (2.58.259).

## 9. План выката (НЕ выполнен, для DevOps)

```bash
cd /var/www/admin_bot
git fetch --prune origin
git status -sb && git rev-parse HEAD          # ожидается 1defb4e05 (2.58.259)
git pull --ff-only                            # до tip ветки release/2.58.260
python tools/release_manifest.py               # effect=deploy, previous=<фактический HEAD>
sudo systemctl restart admin_bot
curl -fsS http://127.0.0.1:8000/healthz        # ожидается version 2.58.260
python manage.py disk audit && python manage.py disk cleanup --apply   # P0-PROD-DISK-01
```

После рестарта: `healthz.version=2.58.260`, `deployed_sha=<фактический HEAD>`,
`.deploy/release.json`, ошибок схемы нет (DDL не ожидается), свободное место.
Наблюдаемые эффекты: (F-STALL-01) при блокировке loop ≥ порога появляется один WARNING
`loop_lag | lag_ms=… threshold_ms=… snapshot_begin … snapshot_end` с
`extra.event=loop_lag` и RAM-дампом стеков, watchdog не блокирует цикл и не повторяет
дамп на каждом тике; (MOD-ACL) mobile-карточка модуля возвращается в контракт 132–164 px
при сохранённом 44-px контроле и без обрезки текста.

## 10. Ограничения и честные пометки

- Деплой не выполнялся; прод не затрагивался (read-only).
- `tools/ui_mod_acl_m4_catalog_e2e.py` в этой сборке **не перезапускался**: файл
  байт-идентичен базе и кандидату, кода сборка не меняла; применим замер review r4 —
  12 failures (8 уникальных × 2 ширины, принятый backlog R4-B1 «устаревшие ожидания
  конверта Опыта»), на базе `9516c9125` — 4 stale; проверки высоты зелёные.
- Визуальные замеры (390/320/1440, coarse 768/1024) не повторялись — используются
  независимые замеры review r4 (Playwright + Browser Use) на том же кандидате; сборка
  этот код не меняла (байтовая идентичность §2).
- Модельное/поведенческое наблюдение watchdog в реальной нагрузке прода — после деплоя;
  детерминированно доказаны срабатывание по порогу, формат события и отсутствие блокировки.
- 10 предсуществующих red остаются backlog'ом (доказано на базе).

## Артефакты

`raw/`: `product-delta.txt`, `identity.txt`, `bump-verify.txt`, `routes-pin.txt`,
`ddl-check.txt`, `f8-check.txt`, `tests-loop-lag.txt`, `tests-modacl-e2e.txt`,
`js-m5c-overlay-unit.txt`, `js-m4-catalog.txt`, `js-w2a-tabs.txt`, `js-module-store.txt`,
`tests-m5b-f5.txt`, `tests-m4.txt`, `tests-m4-base.txt`, `tests-pins.txt`,
`tests-pins-base-red.txt`, `tests-startup-smoke.txt`, `tests-round106-tip.txt`,
`tests-round106-base.txt`, `manifest-deploy.json`, `manifest-rollback.json`,
`manifest-deploy-previous-1defb4e05.json`, `test-sets.json`, `SHA256SUMS`.
