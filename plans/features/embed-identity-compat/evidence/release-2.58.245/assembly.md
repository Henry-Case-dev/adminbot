# Релиз 2.58.245 — сборка (MODEL-SWAP-01..05)

- **Роль:** Builder (локальная сборка). **Без деплоя и SSH** — выкладка и post-deploy за DevOps
  после независимого delta-ревью.
- **База (production 2.58.244):** `5621bda8dd302c19fa7cda29d84c8541c5d2304a`.
- **Ветка:** `release/model-swap-2.58.245` от `5621bda8d` (fast-forward, без merge-коммитов).
- **Независимое ревью:** `plans/features/embed-identity-compat/evidence/model-swap/review-r2.md`,
  sha256 `bee324f1c21cc94a3b73eb2b29a6e03f76585fae45c8bfa23a349185a8bb7c69`,
  verdict **APPROVED_FOR_RELEASE_PREPARATION** для tip `f2a4b6426`
  (product tree `21da28821`), reviewer session `ses_def0673f6ffexiKu658xKuyWTR`.
- **Builder evidence candidate:** `plans/features/embed-identity-compat/evidence/model-swap/implementation-2026-11-25.md`.
- **Строки:** `MODEL-SWAP-01`, `MODEL-SWAP-02`, `MODEL-SWAP-03`, `MODEL-SWAP-04`, `MODEL-SWAP-05`.

```json
{
  "release": "2.58.245",
  "slice": "MODEL-SWAP",
  "rows": ["MODEL-SWAP-01", "MODEL-SWAP-02", "MODEL-SWAP-03",
           "MODEL-SWAP-04", "MODEL-SWAP-05"],
  "base": {"sha": "5621bda8dd302c19fa7cda29d84c8541c5d2304a",
           "version": "2.58.244",
           "state": "deployed_production"},
  "source_branch": "feat/model-swap-2026-11-25",
  "source_product_tip": "21da28821feab5aceaa8ea508e361ff82d698b5c",
  "source_evidence_tip": "f2a4b64267917b80ffab44d467290fd23a52fd2a",
  "review": {"file": "plans/features/embed-identity-compat/evidence/model-swap/review-r2.md",
             "sha256": "bee324f1c21cc94a3b73eb2b29a6e03f76585fae45c8bfa23a349185a8bb7c69",
             "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
             "reviewed_tip": "f2a4b6426"},
  "content_tip": {"sha": "f2a4b64267917b80ffab44d467290fd23a52fd2a",
                  "tree": "87af386a46147b92b5407e0dd100885d4e8f8d61",
                  "commits": 6,
                  "delta_vs_base": {"files": 7, "insertions": 2660,
                                    "deletions": 40}},
  "bump_tip": {"sha": "7aacf17b381843368f0cf8973c832174c45d5e93",
               "tree": "5299737066182735d37973992cecfc4082e7ab2e",
               "version": "2.58.245",
               "delta": {"files": 32, "insertions": 35, "deletions": 35}},
  "total_delta_vs_base": {"commits": 7, "files": 39, "insertions": 2695,
                          "deletions": 75},
  "rollback": {"code_only_sha": "5621bda8dd302c19fa7cda29d84c8541c5d2304a",
               "ddl": 0, "migrations": 0, "flags": 0,
               "data_migration": false, "new_stores": 0},
  "manifest_dry_run": {
    "schema": 1,
    "deployed_sha": "7aacf17b381843368f0cf8973c832174c45d5e93",
    "version": "2.58.245",
    "previous_sha": "5621bda8dd302c19fa7cda29d84c8541c5d2304a",
    "previous_version": "2.58.244",
    "release_branch": "release/model-swap-2.58.245",
    "effect": "deploy",
    "dirty_tracked": false,
    "written": false
  },
  "tests": {
    "model_swap_file": {"total": 19, "passed": 19, "failed": 0},
    "focused_embed_regression": {"total": 268, "passed": 268, "failed": 0},
    "version_and_pin_set": {"total": 860, "passed": 855, "passed_after_flaky_rerun": 855,
                            "failed_deterministic": 5,
                            "failed_flaky_environment": 11,
                            "flaky_passed_on_isolated_rerun": 11},
    "js_version_pins": {"total": 4, "passed": 4, "failed": 0},
    "release_manifest_file": {"total": 20, "passed_clean_runs": 20,
                              "flaky_runs": "environment WinError 6",
                              "run_samples": ["20 passed", "18 failed / 2 passed", "20 passed"]},
    "readme_version_pin": {"total": 1, "failed": 1, "status": "pre-existing on base"},
    "py_syntax": {"files": 31, "ok": 31, "failed": 0},
    "app_js_node_check": {"rc": 0},
    "git_diff_check": {"worktree_rc": 0, "range_rc": 0}
  }
}
```

## 1. Линия и интеграция

- Release-ветка создана от production-базы `5621bda8d` в отдельном worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/release-model-swap-2-58-245-...`, unit
  `release-2.58.245`, epic `release-model-swap-2.58.245`).
- Интеграция — `git merge --ff-only f2a4b6426`: **fast-forward, merge-коммитов нет, правок нет**.
  Слайс уже линеен над `5621bda8d` (merge-base совпадает с базой).
- **Уточнение к диспатчу (честно):** в задании названы 5 коммитов, фактическая линейная
  цепочка над базой содержит **6** коммитов; недостающий в перечне — docs-коммит
  `88193c7af` («MODEL-SWAP-01..05 implementation evidence»), он является родителем
  `ba761b74e` и без него дерево проверенного tip `21da28821` недостижимо. Включён;
  product-дерево совпадает с проверенным (`git diff 21da28821 f2a4b6426` = только evidence-md).

Коммиты слайса над базой:

```text
3e079d26e feat(embed): MODEL-SWAP-01..05 model change flow with background rebuild
88193c7af docs(embed): MODEL-SWAP-01..05 implementation evidence
ba761b74e fix(embed): align model-swap target dimension with served ACTIVE space
4aec98f13 docs(embed): update MODEL-SWAP candidate SHA
21da28821 fix(model-swap): canonical source guard + recoverable failed state + real new dimension in confirm (F1/F2)
f2a4b6426 docs(model-swap): corrective evidence F1-F4
```

- **Content tip:** `f2a4b64267917b80ffab44d467290fd23a52fd2a`
  (tree `87af386a46147b92b5407e0dd100885d4e8f8d61`).
- **Product tip:** `21da28821feab5aceaa8ea508e361ff82d698b5c` (единственный docs-коммит сверху).

## 2. Границы дельты `5621bda8d..7aacf17b3`

| Проверка | Результат |
|---|---|
| Всего файлов | **39**: 7 слайс + 32 bump; `+2695/−75` |
| Слайс `5621bda8d..f2a4b6426` | 7 файлов, `+2660/−40`: `services/graphrag_rebuild.py` (+791/−…), `web/api/memory_agi.py` (+322), `web/app.js` (+306), `web/index.html` (+198), `services/embedding_control_plane.py` (+22/−…), `tests/test_embed_model_swap_ux.py` (новый, 991), evidence-md (новый, 70) |
| Bump | ровно **32** файла, `+35/−35` — только `APP_VERSION`/version pins (§3) |
| `migrations/` | **0** |
| `config/` | только `config/settings.py` (строка `APP_VERSION`) |
| Новые флаги (`ClassVar[bool]`) | **0** |
| `requirements.txt`, `prompts/`, `services/database.py` | **0** |

Схема остаётся **v48 / DDL 0**, миграций и изменений данных нет.

## 3. Bump 2.58.244 → 2.58.245

`7aacf17b3` — **standard version wave**, ровно тот же набор, что bump 2.58.244 (`93102d860`):
32 файла, `+35/−35`.

| Группа | Файлы |
|---|---|
| `APP_VERSION` + release-клауза | `config/settings.py` (1 строка: `2.58.245` + новая клауза, прежняя голова стала `Prior (25.11.2026): 2.58.244 - …`) |
| F8 meta | `plans/docs/param-registry-round1025.meta.md` |
| py-пины (`APP_VERSION == "2.58.245"`) | 24 теста `round1025/1026`, 2 инструмента `ui_mod_acl_m4b*` |
| JS-пины (escaped `2\.58\.245`) | `round1025_hotfix{7,8,9,10}_*_test.js` |

**Проверено, что bump — только версия:** каждая из 35 изменённых строк отличается от прежней
исключительно токеном версии (для `settings.py` — новый префикс + вставленная клауза, хвост
байт-идентичен); скрипт-проверка: 32 файла, 35 строк, **0** не-версионных отличий.
BOM и EOL сохранены (byte-level замена; `config/settings.py` — CRLF+BOM, в проверке 3665 CRLF/0 LF).
`git diff --check` — rc 0 (worktree и `5621bda8d..HEAD`).

Исторические файлы `2.58.244` (`plans/features/vmq-onto-01/evidence/release-2.58.244/*`,
`evidence/model-swap/implementation-2026-11-25.md`) **не менялись**.

## 4. Manifest dry-run

Чистое tracked-дерево `7aacf17b3`; `.deploy/release.json` (gitignored) временно содержал
production-манифест `5621bda8d / 2.58.244` для честного `previous`:

```json
{
  "schema": 1,
  "deployed_sha": "7aacf17b381843368f0cf8973c832174c45d5e93",
  "version": "2.58.245",
  "deployed_at": "2026-11-25T05:21:28.368890Z",
  "effect": "deploy",
  "previous_sha": "5621bda8dd302c19fa7cda29d84c8541c5d2304a",
  "previous_version": "2.58.244",
  "release_branch": "release/model-swap-2.58.245",
  "dirty_tracked": false
}
```

`--dry-run` rc 0, файл не записан (seed остался нетронутым), seed удалён после прогона.
Дополнительно `--effect rollback --dry-run` rc 0 (та же identity, `effect=rollback`).
DevOps повторяет manifest на **точном deployed SHA**.

## 5. Тесты на bumped tip `7aacf17b3`

Окружение: глобальный Python 3.12 (`C:\Users\main\AppData\Local\Python\bin\python.exe`),
`PYTHONPATH=<worktree>`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`.

| Прогон | Результат |
|---|---|
| `pytest tests/test_embed_model_swap_ux.py -q` | **19 passed** (72.21 s) — включая Playwright UI 1440/390 |
| Focused embed/generation: `test_graphrag_identity_reindex`, `test_embed_simplify_2026_11_24`, `test_embed_identity_compat_restart_legacy`, `test_p0_embed_admission_msi`, `test_p0_embed_503_failover`, `test_embed_identity_compat`, `test_asap6_embedding_generations`, `test_summary_memory`, `test_embedding_control_plane_asap4`, `test_webapp_memory_overview_api` | **268 passed** (50.83 s) |
| Version/pin-набор (24 файла, содержащие пин версии) | прогон 1: **855 passed / 5 failed** (74.44 s); прогон 2: 843 passed / 16 failed / 1 skipped. 11 «лишних» падений — флейки окружения (§7), в изолированном повторе **11 passed** |
| Registry/param-catalog/route-пины: `test_round1025_f8_registry`, `test_webapp_f11_round1025`, `test_scope_selector_round1025`, `test_webapp_design_tokens_round1025`, `test_webapp_round1026_polygon` | 142 passed / 4 flaky (node-subprocess) → повтор **56 passed, 0 failed** |
| 4 JS version-pin теста (`node --test`) | **4 pass, 0 fail** |
| `tests/test_release_manifest.py` | 3 прогона: **20 passed**, 18 failed (флейк), **20 passed** — §7 |
| README-пин `test_webapp_round108_ui::…::test_app_version_matches_readme` | **1 failed** — pre-existing, §6 |
| Синтаксис: 31 изменённый `.py` (in-memory `compile`) | **31 ok, 0 errors** |
| `node --check web/app.js` | rc 0 |
| `git diff --check` (worktree и диапазон) | rc 0 / rc 0 |

## 6. Pre-existing (воспроизведено на базе `5621bda8d`, не правилось)

Проверено прогоном тех же тестов в отдельном detached-worktree на `5621bda8d`
(после проверки worktree удалён) и tree-to-tree сверкой:

1. `test_tool_coordinator_round1026::TestBounds::test_canon_twelve_tools` — `assert 18 == 17`
   (набор инструментов вырос после round1026, `inspect_runtime` и др.).
2. `test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff` —
   в diff от старого baseline `e8646af` присутствуют не внесённые в allowlist пути
   `web/api/access.py`, `web/api/avatars.py`, `web/request_status.py`, `web/static/status-analytics.js`
   (те же 4 пути уже отличаются от baseline на базе: `git diff --name-only e8646af 5621bda8d`).
3. `test_unified_image_request_round1026::TestToolDescriptionU21::test_canon_unchanged` —
   «Left contains 2 more items» (`inspect_runtime`, …).
4. `test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` —
   те же 4 пути.
5. `test_webapp_f9_round1025::TestInvariants::test_secrets_count_28` — `assert 34 == 32`
   (секрет-полей стало больше после round1025).

Значения утверждений на базе идентичны (`18 == 17`, `34 == 32`) — падения не связаны ни со
слайсом, ни с bump. Слайс не добавлял ни инструментов, ни секрет-полей, ни этих четырёх путей.

Дополнительно: README-пин (`test_app_version_matches_readme`) падает на базе так же —
README содержит `v2.57.0`.

## 7. Флейки окружения (не дефект кандидата)

Тесты, порождающие подпроцессы (`git show <baseline>`, `node --check`, `node --test`),
периодически падают с `OSError: [WinError 6] Неверный дескриптор` в
`subprocess._make_inheritable` — сбой наследования stdio в этой Windows-сессии, до обращения
к содержимому репозитория. Доказательство недетерминизма на **одном и том же** дереве:

- `test_release_manifest.py`: `20 passed` → `18 failed / 2 passed` → `20 passed` (3 прогона подряд);
- pin-набор: 5 failed → 16 failed → изолированный повтор 11 «новых» падений — **11 passed**;
- `test_webapp_f11_round1025` + `test_webapp_round1026_polygon`: 4 failed → повтор **56 passed**.

Детерминированными остаются только 5 падений из §6.

## 8. Rollback

- **Code-only:** `5621bda8dd302c19fa7cda29d84c8541c5d2304a` (2.58.244),
  `tools/release_manifest.py --effect rollback`.
- **DDL 0, миграций 0, флагов 0**, новых хранилищ 0: данные и настройки не мигрируются и не
  откатываются. Схема остаётся v48. `requirements.txt` не менялся.
- Единственный durable-маркер слайса — `config_revision = "model_swap:<source_msi>"` в
  существующей строке generation; при откате кода не читается и не мешает.

## 9. Что должно оценить delta-ревью

1. **Первый живой код смены модели эмбеддингов.** Flow MODEL-SWAP впервые попадает в
   production: `services/graphrag_rebuild.py` (+791), `web/api/memory_agi.py` (+322),
   `web/app.js`/`web/index.html` (+306/+198), новый тест-файл. Продуктовое ревью r2 —
   APPROVED_FOR_RELEASE_PREPARATION, но delta-ревью должно подтвердить, что в релизную ветку
   попал именно проверенный slice и ничего сверх него (7 файлов, §2).
2. **Реальная смена модели — postdeploy-действие, не часть релиза.** Релиз выкладывает
   механизм; фактический switch модели/размерности и пересборка индекса выполняются после
   деплоя (агентами, не владельцем). Live-доказательство MODEL-SWAP-03/04/05 остаётся
   `delivered_awaiting_evidence`; MODEL-SWAP-01/02 требовали preprod-live, который **не
   выполнялся** (production-доступ в этой задаче запрещён). Это надо назвать в решении
   честно, а не закрывать как VERIFIED.
3. **Docs-коммиты слайса включены** (`88193c7af`, `4aec98f13`, `f2a4b6426`) — они меняют только
   evidence-md под `plans/features/embed-identity-compat/evidence/model-swap/`; product-байты
   от них не меняются. При этом в диспатче перечислены 5 коммитов вместо 6 (§1).
4. **Bump — 32 файла / 35 строк, только версия** (§3): стоит подтвердить выборочно, что
   registry/param-catalog/route-пины не «подкручены» под версию (они не менялись по смыслу,
   только строковый токен), и что `config/settings.py` не получил функциональных правок.
5. **5 pre-existing падений** (§6) не блокируют релиз, но остаются долгом тестового набора:
   исторические пины round1025/1026 устарели относительно текущего кода и уже падали на
   production-базе 2.58.244.

## 10. Остаточное (не блокирует)

1. Preprod-live для MODEL-SWAP-01/02 не выполнялся (запрет на production-доступ в задаче);
   live-проверка — шаг DevOps/preprod после выкладки.
2. MS-R1-B1 (прямой `POST /api/config` мимо UI во время активного swap) остаётся BACKLOG_ONLY
   по решению ревью r2; безопасность обеспечивается теневым индексом и отменой failed-swap.
3. Флейки окружения (§7) относятся к локальной Windows-сессии, не к коду; на чистом прогоне
   набор зелёный.
4. Playwright-проверки UI в `test_embed_model_swap_ux.py` используют реальные
   `web/index.html` + `web/app.js` с route-stubbed API (mock-DTO), не live `/api/status`;
   live-вид проверяется post-deploy.
