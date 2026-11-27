# Release 2.58.262 — сборка из двух независимо одобренных срезов

- **Дата:** 2026-11-28
- **Роль:** Builder (сборка релиза, **без деплоя**)
- **Статус:** ASSEMBLED, не задеплоен. Деплой — DevOps/Orchestrator.
- **База (deployed):** `f0dc7d87841a6f3089fb4153474768f34c567e22` = **2.58.261**.
  Read-only подтверждение прода на момент сборки:
  `GET https://admin-bot.duckdns.org/healthz` → HTTP 200 `{"status":"ok","version":"2.58.261"}`.
- **Ветка:** `release/2.58.262`
- **Tip продукта (bump):** `9d592ac6ffb0f05f0b6eb7b918903f8e0c15166b`
- **Tree продукта (bump):** `35a1a53a884084721bf20f2c0ec9d52373a0c25b`
- **Сборка:** evidence-коммит поверх bump (docs-only): `git diff 9d592ac6f HEAD -- services/ tests/ web/ bot.py manage.py config/ tools/` пусто,
  меняется только `plans/**`.

## 0. Состав (оба среза одобрены независимым Reviewer)

| Срез | Reviewed-кандидат | Вердикт / evidence |
|---|---|---|
| Speech / personality corrective | код `b404d7b1f4e8b6cf3f289d1831c3c3f595425841`, evidence tip `80d1cb625` | `plans/features/speech-applicability-core-ux-01/evidence/review-r3/review-r1.md`, sha256 `103440c60b3b633765d63d1ffab1d5af486694ea20cd3e7d91b3953a54c70c8c` — APPROVED_FOR_RELEASE_PREPARATION (re-review r4, master `ff2e2265c`) |
| row_media_marker (NameError) | tip `583840fb1527d281cd5d9ab625e88d03f1fc5775`, код `449e9ee34` | `plans/features/p0-row-media-marker-nameerror-01/evidence/2026-11-28/review-r1/review-r1.md`, sha256 `aba89dff2b6e5cab36f327878f503da20e006c8b7f9a62e3241d41ca073d29db` — APPROVED_FOR_RELEASE_PREPARATION (master `d4e8c05f5`) |

## 1. Cherry-pick (`-x`) поверх базы, reviewed-код не менялся

Конфликтов **не было ни одного** (включая `web/api/routes.py` — на базе файл побайтово совпадал с точкой ветвления `886d11073`, поэтому хунк применился чисто).

Speech-срез (`886d11073..80d1cb625`, 8 коммитов):

| Новый коммит | Исходный |
|---|---|
| `a7aac34d7` | `0f59db8e1` feat(personality): single Core on Persona tab, speech applicability without temperature gate |
| `40abd571c` | `57433d89b` fix(speech): SAC-REV-R1 F1/F2 |
| `af5576792` | `d8303f45c` test(speech): SAC-REV-R1 F1 behavioral JS test + F2b e2e |
| `b33b85189` | `2d4bb2427` test(ui): SAC-REV-R1B-F2 snapshots |
| `082315e80` | `45785082c` docs(speech): corrective r2 evidence |
| `ee681a939` | `1b28fa4d6` docs(speech): corrective r2 screenshots |
| `abcb8c262` | `b404d7b1f` fix(ui): SAC-REV-R2-F1 retry latch reset |
| `86d635985` | `80d1cb625` docs(speech): corrective r3 evidence |

row_media_marker (`0df7f4da2..583840fb1`, 3 коммита):

| Новый коммит | Исходный |
|---|---|
| `6557edc07` | `0df7f4da2` test(p0-row-media-marker): RED |
| `8e022b251` | `449e9ee34` fix(p0-row-media-marker): import row_media_marker |
| `a432b11ef` | `583840fb1` docs(p0-row-media-marker): evidence |

Затем `9d592ac6f` — bump.

## 2. Байтовая идентичность reviewed-коду

`raw/identity.txt`, `raw/identity-merge.txt`.

- **row_media_marker: 11/11 файлов побайтово** равны `583840fb1`;
  `services/direct_chat_service.py` = `e74b9bda2f2beb765634d708202e35d53380ec3b` (= `449e9ee34`, = `583840fb1`). **BYTE_IDENTICAL_ROW_MEDIA=True.**
- **speech-срез: 18 из 22 файлов побайтово** равны reviewed-кандидату
  (`b404d7b1f` для кода/тестов, `80d1cb625` для evidence): `web/api/routes.py`,
  `tests/test_speech_applicability_core_ux.py`, `tests/js/speech_core_scope_ctx_test.js`,
  `tests/ui_p0a_ux_speech_compact_e2e.py`, `tests/test_webapp_js_unit.py`,
  `tests/js/prompt_version_card_test.js`, `tests/js/ur_ui_settings_test.js`,
  `tests/ui_prompt_version_card_e2e.py`, evidence `corrective-r2*`, `evidence.md` и др.
  `web/api/routes.py` blob `a851e4f857b13ea1851ebfcc00aec940b867a896` = `b404d7b1f`.
- **4 файла отличаются, и это ожидаемо** (доказано 3-way merge, `raw/identity-merge.txt`):
  `web/app.js`, `web/index.html`, `web/static/app.css`, `tests/test_round1025_f8_registry.py`.
  База `f0dc7d878` независимо продвинула их после точки ветвления (mod-acl r2/r3 correctives,
  4 коммита: `53bf8d417`, `36483d6af`, `3fb790d64`, `99dca746c`).
  Независимый `git merge-tree --merge-base=886d11073 b404d7b1f f0dc7d878` = tree
  `17b9d67f32c8364130e688d55bded15bd4602a61`; HEAD-блобы **совпадают с merge-результатом**
  для `web/app.js` (`2f6d956de9b8`), `web/index.html` (`3848bfa092ce`),
  `web/static/app.css` (`0aa98f6efa24`) — ни один reviewed-хунк не потерян, конфликтов нет,
  изменения базы сохранены. `tests/test_round1025_f8_registry.py` равен тому же merge плюс
  строка bump (`APP_VERSION == "2.58.261"` → `"2.58.262"`), других отличий нет.
- `services/bot_persona.py` (`274641f65046…`) и `services/prompt_composer.py` (`fb73d1455e3e…`)
  в этом релизе **не меняются**: блобы равны и базе, и кандидату `b404d7b1f` (Δ=0).

## 3. Routes-пин (ROUTES_SHA256_F11)

`raw/routes-pin.txt`, `raw/routes-tests.txt`.

```
routes_sha256_head                    = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
routes_sha256_base_f0dc7d878          = 6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
routes_blob_head = routes_blob_reviewed_b404d7b1f = a851e4f857b13ea1851ebfcc00aec940b867a896
ROUTES_SHA256_F11                     = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
pin_matches_head=True  pin_equals_expected_candidate=True
```

Re-pin приехал самим reviewed-коммитом `0f59db8e1`/`b404d7b1f` (комментарий SAC-S1 в
`tests/test_round1025_f8_registry.py`), руками пин не правился. Тесты:
`test_routes_file_unchanged` PASSED, `test_routes_set_unchanged` PASSED,
`test_routes_sha256_f11_intact` PASSED (3 passed).

## 4. Bump 2.58.261 → 2.58.262 — version-only

`raw/bump-verify.txt`:

```
bump_commit=9d592ac6ffb0f05f0b6eb7b918903f8e0c15166b  parent=a432b11ef958de827ada0ffa807e6d9a74cf9626
files=29  additions=34  deletions=34
non_version_changed_lines=0
pairs_differing_only_by_version=34 / 34
version_only_bump=OK
eol_settings_base_2.58.261: crlf=3665 bare_lf=0 size=362807
eol_settings_tip_2.58.262:  crlf=3665 bare_lf=0 size=362807
APP_VERSION tip: APP_VERSION = "2.58.262"
```

Набор файлов идентичен bump 2.58.260→2.58.261 (те же 29 путей: `config/settings.py`,
`plans/docs/param-registry-round1025.meta.md`, 25 тестов, 2 tools). CRLF сохранён,
размер `config/settings.py` не изменился.

## 5. DDL = 0, `user_version` 49

`raw/ddl-check.txt`:

```
changed_migrations_or_pg_db=[]
migrations_dir_exists=False
services/database.py_changed=False
services/database.py_added_lines=0
ddl_keyword_hits_in_database.py_added_lines=[]
max_schema_constant=49 (_SCHEMA_VERSION_SELF_DIAG_SAMPLES)
user_version_target=49
ddl_delta=0
```

Миграций нет, схема не меняется → **rollback code-only**.

## 6. Проверки (cwd = release-worktree, `C:\Code\Python\adminbot\.venv\Scripts\python.exe`,
`node v24.16.0`; прод не затрагивался)

| Прогон | Результат | Raw |
|---|---|---|
| `tests/test_speech_applicability_core_ux.py` | **15 passed** (10.4 s) | `tests-speech.txt` |
| `node tests/js/speech_core_scope_ctx_test.js` | **SPEECH-CORE-SCOPE-CTX-OK** (exit 0) | `js-speech.txt` |
| `tests/ui_p0a_ux_speech_compact_e2e.py` | **failures=0, POST=21** | `tests-e2e-p0a.txt`, `e2e-p0a.json` |
| `tests/test_webapp_js_unit.py` | **43 passed, 7 failed** — те же 7 node id, что на базе (см. §7) | `tests-webapp-js-unit.txt` |
| `tests/test_p0_row_media_marker_live_selection.py` | **2 passed** | `tests-row-media.txt` |
| `test_direct_chat*` (6 файлов) + `test_ur_c_3_real_fts.py` | **316 passed** (26.1 s) | `tests-direct-chat-fts.txt` |
| Пины: `test_round1025_f8_registry.py` + `test_asap7_cover_preview.py` + `test_webapp_f11_round1025.py` | **83 passed** (10.5 s) | `tests-pins.txt` |
| Пины точечно (routes file/set/sha256) | **3 passed** | `routes-tests.txt` |
| Реестр: `tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 659 == REGISTRY** | `registry-check.txt` |
| Стартовый smoke (10 файлов: `test_smoke_round1016_*` ×8, `test_monitoring_smoke`, `test_webapp_parity_smoke`) | **86 passed** (11.0 s) | `tests-startup-smoke.txt` |

## 7. Предсуществующие red-ы (сверка с базой `f0dc7d878`)

Единственный набор с red-ами — `tests/test_webapp_js_unit.py`. База: **42 passed, 7 failed**
(`raw/base-reds-js-unit.txt`), кандидат: **43 passed, 7 failed** — те же 7 node id,
+1 новый passing-тест из speech-среза (`d8303f45c` добавил 10 строк в этот файл):

- `test_js_unit_routing_and_scope_guard`
- `test_js_unit_round1024_image_key`
- `test_js_unit_round1025_hotfix7_shell_glass_heartbeat`
- `test_js_unit_round1025_hotfix8_shell_aurora`
- `test_js_unit_round1025_hotfix9_shell_flex_glass_aurora`
- `test_js_unit_round1025_hotfix10_glass_geometry_bg`
- `test_js_unit_round1025_f7_permsoc_local`

Все остальные прогоны — без падений, сравнивать с базой по node id не требуется.

## 8. Manifest dry-run (не деплой)

`.deploy/release.json` в worktree отсутствует (gitignored); для dry-run использован
временный stub «текущий прод = 2.58.261 @ f0dc7d878», после прогона `rm -rf .deploy`
(проверено: каталога нет).

```
raw/manifest-deploy.json
{ "deployed_sha": "9d592ac6ffb0f05f0b6eb7b918903f8e0c15166b",
  "version": "2.58.262", "effect": "deploy",
  "previous_sha": "f0dc7d87841a6f3089fb4153474768f34c567e22",
  "previous_version": "2.58.261",
  "release_branch": "release/2.58.262", "dirty_tracked": false, "schema": 1 }
raw/manifest-rollback.json — effect=rollback, тот же previous_* (f0dc7d878 / 2.58.261).
```

**Rollback = code-only** (DDL Δ=0, схема v49).

## 9. Инструкция DevOps (выполняет не Builder)

```bash
cd /var/www/admin_bot
git fetch --prune origin
git status -sb && git rev-parse HEAD        # ожидается f0dc7d878 (2.58.261)
git pull --ff-only                          # tip release/2.58.262
python tools/release_manifest.py            # effect=deploy, previous=f0dc7d878 / 2.58.261
sudo systemctl restart admin_bot
curl -fsS http://127.0.0.1:8000/healthz     # ожидается version 2.58.262
python manage.py disk audit && python manage.py disk cleanup --apply
```

После выката проверить effective-state: `ROUTES_SHA256_F11` соответствует факту,
карточка Core на вкладке «Персона» одна, техническая пометка temperature только у
float-значений, `/api/config` не отдаёт `status=inactive` селектору
`limits.chat_temperature_preset_default`; `_context_row_line` с медиа-строкой без подписи
не даёт NameError в логах.

## 10. Ограничения

- Деплой **не выполнялся**; прод остаётся 2.58.261 (healthz read-only, 200).
- UI e2e — playwright с route-mock на `/api/*` и локальным webroot, не реальный прод-API;
  реальные мобильные устройства и живой Telegram не проверялись (и не требуются контрактом).
- 7 red-ов `test_webapp_js_unit.py` предсуществующие и не связаны с релизом (BACKLOG_ONLY,
  вне scope); они воспроизведены на базе тем же набором node id.
- Карты/`progress_scope.json` не изменялись; evidence добавлено только в `plans/features/**`.

## Приложения

`raw/`: `identity.txt`, `identity-merge.txt`, `changed-files.txt`, `product-delta.txt`,
`bump-verify.txt`, `routes-pin.txt`, `routes-tests.txt`, `ddl-check.txt`,
`tests-speech.txt`, `js-speech.txt`, `tests-e2e-p0a.txt`, `e2e-p0a.json`,
`tests-webapp-js-unit.txt`, `base-reds-js-unit.txt`, `tests-row-media.txt`,
`tests-direct-chat-fts.txt`, `tests-pins.txt`, `registry-check.txt`,
`tests-startup-smoke.txt`, `manifest-deploy.json`, `manifest-rollback.json`, `SHA256SUMS`.
