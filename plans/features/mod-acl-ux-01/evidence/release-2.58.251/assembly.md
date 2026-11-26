# Сборка 2.58.251 — MOD-ACL-UX-01 M1-B (единый предикат «глобальный админ» в чате)

- **Роль:** Builder, локальная сборка. **Без deploy, merge в master, SSH и
  production.** Effective-state прода и post-deploy проверки — DevOps после
  выкладки; этот документ — вход для delta-ревью релизного кандидата.
- **База (production 2.58.250):** `a64ecb89b0a5930bb37e9a6e73931174f7a8e7ba`.
- **Ветка:** `release/mod-acl-m1b-2.58.251` от `a64ecb89b` в registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/mod-acl-ux-01-1e46be007668-a833f258`,
  epic `mod-acl-ux-01`, unit `m1b-release`). Интеграция — линейные cherry-pick,
  **без merge-коммитов**.
- **Срез:** `MOD-ACL M1-B`, ветка `feat/mod-acl-m1b`, tip
  `b070382b15844d3d5b2692a83a8cf078860a70f5` (функциональный коммит
  `1704c2e62`, evidence-коммит `b070382b1`). Ревью r1:
  `plans/features/mod-acl-ux-01/evidence/m1/m1b-review-r1.md`, sha256
  `2d226501f77381215244b9b51c29d97f55182eb46c5137d11f4fe709ea006a0a`
  (воспроизведён на planning-checkout), вердикт
  `APPROVED_FOR_RELEASE_PREPARATION`.
- **Строки:** `MAC-S4-174` — **MET** (закрывается инкрементом). `MAC-S4-172`,
  `MAC-S4-171`, `MAC-S10-13` — осознанно остаются **PENDING** (ревью прямо
  запрещает привязку их как VERIFIED на этом инкременте).

```json
{
  "release": "2.58.251",
  "base": {"sha": "a64ecb89b0a5930bb37e9a6e73931174f7a8e7ba", "version": "2.58.250"},
  "slice": {
    "id": "MOD-ACL-UX-01 M1-B",
    "name": "единый предикат глобального админа в чате (MAC-S4-174)",
    "branch": "feat/mod-acl-m1b",
    "base": "a64ecb89b0a5930bb37e9a6e73931174f7a8e7ba",
    "source_tip": "b070382b15844d3d5b2692a83a8cf078860a70f5",
    "product_commit": "1704c2e62",
    "review": {
      "r1": "plans/features/mod-acl-ux-01/evidence/m1/m1b-review-r1.md",
      "r1_sha256": "2d226501f77381215244b9b51c29d97f55182eb46c5137d11f4fe709ea006a0a",
      "hash_reproduced": true,
      "verdict": "APPROVED_FOR_RELEASE_PREPARATION",
      "reviewer_session": "ses_deaef8030ffeBAboRzWrRM1qOU"
    },
    "per_row": {
      "MAC-S4-174": "MET",
      "MAC-S4-172": "PENDING",
      "MAC-S4-171": "PENDING",
      "MAC-S10-13": "PENDING"
    }
  },
  "integration": "linear cherry-pick: slice (2 commits), version wave (1)",
  "integration_commits": 3,
  "commits_above_base": 4,
  "pre_bump_head": "0d4c99079",
  "pre_bump_tree": "61f6ef2838a591fac6bf705f6766b3351af32de1",
  "bump_commit": "1647fe132",
  "delta_vs_base_at_code_candidate": {"files": 45, "insertions": 2207, "deletions": 46}
}
```

`delta_vs_base_at_code_candidate` измерен на `1647fe132` (срез + version wave) и
подтверждается `git diff --shortstat a64ecb89b 1647fe132`. С этим
evidence-документом итоговый tip ветки добавляет ровно один файл в `plans/`
(этот документ), поэтому общий delta tip'а = delta код-кандидата + 1 файл.

## 1. Порядок интеграции

| # | интеграционный SHA | источник | тип |
|---|---|---|---|
| 1 | `7e0aa831c` | `feat/mod-acl-m1b` `1704c2e62` | product + tests + evidence (MAC-S4-174) |
| 2 | `0d4c99079` | `feat/mod-acl-m1b` `b070382b1` | evidence (фактический статус полного набора, гигиена) |
| 3 | `1647fe132` | — | version wave 2.58.251 |
| 4 | этот документ | — | evidence сборки (только `plans/`) |

`commits_above_base` = 4 на итоговом tip'е; интеграционных (без этого
evidence-документа) — 3.

Cherry-pick прошли без конфликтов; ручных правок кода среза при сборке не
потребовалось. Порядок — ровно как в ветке среза (линейный).

## 2. Файлы среза: побайтовая идентичность

Срез затрагивает **13 файлов** (`git diff --name-status a64ecb89b..b070382b1`:
1 product, 2 теста, 10 evidence). Проверка механическая (`git rev-parse`
blob'ов на pre-bump HEAD против tip'а среза):

| файл | blob (12) pre-bump HEAD | blob (12) `b070382b1` |
|---|---|---|
| `services/chat_access.py` | `e435fd829d42` | `e435fd829d42` |
| `tests/test_chat_access.py` | `39604501e4cf` | `39604501e4cf` |
| `tests/test_mod_acl_ux_01_m1_predicate.py` | `25cc3e7dc071` | `25cc3e7dc071` |
| `plans/.../evidence/m1/m1b/README.md` | `dae364803d83` | `dae364803d83` |
| `plans/.../evidence/m1/m1b/base-same-13.txt` | `87ab8a7a349c` | `87ab8a7a349c` |
| `plans/.../evidence/m1/m1b/full-suite-attempt1-aborted.txt` | `e4e4ca8c4ccb` | `e4e4ca8c4ccb` |
| `plans/.../evidence/m1/m1b/full-suite-attempt2-stopped-5pct.txt` | `bc74a2829aeb` | `bc74a2829aeb` |
| `plans/.../evidence/m1/m1b/green-increment.txt` | `07bf6449229a` | `07bf6449229a` |
| `plans/.../evidence/m1/m1b/red-base-pytest.txt` | `5ae4c583e6ee` | `5ae4c583e6ee` |
| `plans/.../evidence/m1/m1b/red-base-sha.txt` | `bff8ed09877f` | `bff8ed09877f` |
| `plans/.../evidence/m1/m1b/scoped-failed.txt` | `b8ae0d2c4d6d` | `b8ae0d2c4d6d` |
| `plans/.../evidence/m1/m1b/scoped-files.txt` | `a805577aff98` | `a805577aff98` |
| `plans/.../evidence/m1/m1b/scoped-regression.txt` | `83ff6b70a5fd` | `83ff6b70a5fd` |

Итог: **13/13 файлов байт-в-байт равны blob'у среза**. Дополнительно:
`git diff --stat b070382b1 0d4c99079` пуст, деревья совпадают
(`b070382b1^{tree}` = `0d4c99079^{tree}` = `61f6ef2838a591fac6bf705f6766b3351af32de1`).

Требуемые неизменными файлы равны базе:

| файл | blob (12) `a64ecb89b` | blob (12) HEAD | результат |
|---|---|---|---|
| `web/api/deps.py` | `509b387d4894` | `509b387d4894` | идентичен |
| `services/roles.py` | `050728939899` | `050728939899` | идентичен |

## 3. Version wave 2.58.251 (32 файла / 35 строк)

Байтовая замена только токенов версии; BOM/переводы строк сохранены
(`config/settings.py`: BOM `EF BB BF` на месте, 3665 CRLF / 3665 LF / 0 bare-CR —
как на базе). Проверка обратной заменой (`2.58.251 → 2.58.250` плюс обратная
подстановка головы `APP_VERSION`-строки для `config/settings.py`) даёт
**byte-в-byte blob базы для каждого файла: 32/32 reverse-byte-identical,
расхождений 0**.

- `config/settings.py` — 1 строка: `APP_VERSION = "2.58.251"` + релизная заметка
  этого выпуска в той же строке; запись 2.58.250 стала
  `Prior (26.11.2026): 2.58.250 - UR-G/UR-B ...`;
- `plans/docs/param-registry-round1025.meta.md` — 1 (`APP_VERSION`);
- 4 × `tests/js/*` — 4 (экранированный пин `2\.58\.NNN`);
- 24 py-файла пинов — 25 (23 × 1 + `test_webapp_round1026_polygon.py` 2);
- `tools/ui_mod_acl_m4b2_status_e2e.py` 3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1.

Итог: **32 файла, 35 строк**: `git diff --shortstat 0d4c99079 1647fe132` →
`32 files changed, 35 insertions(+), 35 deletions(-)`. Форма ровно как у 2.58.250.

JS-пины `?v=` в `web/index.html` — шаблон `__APP_VERSION__` (не литерал),
отдельных правок не требуют; проверены тестами пинов. Исторические
комментарии `release 2.58.249/2.58.250` в тестах не bump'ились — они описывают
уже выпущенные релизы.

## 4. Производные артефакты: переэмиссия не требуется

- `services/param_catalog.py` — **0 diff** (`git diff --stat a64ecb89b HEAD -- services/param_catalog.py` пуст).
- F8 TSV/карта — **0 diff**: `plans/docs/param-registry-round1025.tsv` (429 838 B),
  `plans/docs/screen-map-round1025.md` (147 091 B), `plans/docs/widget-map-round1025.md`
  не изменялись; единственное изменение в F8-наборе — строка `APP_VERSION` в
  `param-registry-round1025.meta.md` (входит в version wave).
- Frozen-артефакты — **0 diff**: `tests/fixtures/round1025/f8_baseline.json`,
  `tests/fixtures/round1025/catalog_baseline.json` и hash-константы
  (`ROUTES_SHA256_F11`, `PG_DB_SHA256_B07`) не менялись; в
  `tests/test_round1025_f8_registry.py` изменена ровно 1 строка (`APP_VERSION`),
  `git diff --numstat` = `1 1`.
- `python tools/gen_param_registry_round1025.py --check` → **CHECK OK**: реестр
  659 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.
- Счётчики каталога не изменились (REGISTRY 659 / GROUPS 121 / TAB_RULES 23);
  новых флагов/ParamSpec нет. Hand-edit производных не выполнялся.

## 5. Тесты на точном кандидате `1647fe132`

Прогон в worktree сборки, интерпретатор `C:\Code\Python\adminbot\.venv`
(Python 3.12, pytest), `-p no:cacheprovider`.

| набор | passed | failed |
|---|---|---|
| `tests/test_chat_access.py` + `tests/test_mod_acl_ux_01_m1_predicate.py` | **40** | 0 |
| 62-файловый набор затронутых швов (`pytest @scoped-files.txt`, как в ревью) | **2304** | **13** (pre-existing, см. 5.1) |
| пины версии: 24 py-файла волны + `config/settings.py` + 2 tools | **855** | **5** (pre-existing, те же id, что на 2.58.250) |
| ACL/RBAC/secret-наборы (`test_access`, `acl_global_admin_role_permission_gate`, `chat_access`, `dm_access`, `log_ring`, `chat_keys`, `debug_config`, `byok_image_key`, `webapp_access_effective`, `webapp_access_write_safety`, `release_manifest`) | **361** | **1** (pre-existing, см. 5.1) |
| JS: 4 изменённых `tests/js/round1025_hotfix*_test.js` | 4/4 `node --check` rc 0 | 0 |
| структурное: `node --check web/app.js` | rc 0 | 0 |
| структурное: `py_compile` всех 30 изменённых `.py` (base..HEAD) | 30/30 ok | 0 |
| структурное: `git diff --check` (worktree) | rc 0 | 0 |
| структурное: `git diff --check 0d4c99079 1647fe132` (version wave) | rc 0 | 0 |
| структурное: `tools/gen_param_registry_round1025.py --check` | CHECK OK | 0 |

### 5.1 Падения: доказательство идентичности базе

База `a64ecb89b` прогнана в отдельном чистом worktree
(`.../unified-reply-41500c30aca7-4b645e38`, HEAD `a64ecb89b093`, `git status`
пуст) тем же интерпретатором; списки `FAILED` сравнены построчно
(`Compare-Object`, 0 различий).

| набор | на кандидате `1647fe132` | на базе `a64ecb89b` |
|---|---|---|
| те же 13 node id (`@scoped-failed.txt`) | **13 failed** | **13 failed**; `only candidate: []`, `only base: []` |
| 24 pin-файла версии + settings + 2 tools | **5 failed / 855 passed** | **5 failed / 855 passed**, тот же список |
| `tests/test_chat_keys.py::test_parallel_generate_usage_attributed_per_chat` | **1 failed** (`TypeError` в `services/llm_client.py:2203`) | **1 failed**, тот же |

Пять падений пинов (идентичны базе):
`test_tool_coordinator_round1026::TestBounds::{test_forbidden_paths_out_of_diff,
test_canon_twelve_tools}`,
`test_unified_image_request_round1026::{TestToolDescriptionU21::test_canon_unchanged,
TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline}`,
`test_webapp_f9_round1025::TestInvariants::test_secrets_count_28` (34 != 32).

Новых падений относительно базы нет; ни один пин не подгонялся.

### 5.2 `git diff --check` по диапазону base..HEAD

`git diff --check a64ecb89b HEAD -- . ':(exclude)plans/features/mod-acl-ux-01/evidence/m1/m1b/'`
→ **rc 0**: продуктовый код, тесты, пины и version wave чисты. Предупреждения
появляются только внутри трёх evidence-логов среза
(`m1b/README.md` — пустая строка в конце файла, `m1b/red-base-pytest.txt` и
`m1b/scoped-regression.txt` — trailing whitespace в дословно сохранённом выводе
pytest). Это артефакт evidence-файлов, унаследованный **побайтово** от
одобренного tip'а `b070382b1`; правка нарушила бы обязательную byte-identity
и не является дефектом продукта. Не исправлялось, зафиксировано как
BACKLOG-level косметика evidence (не блокер релиза).

## 6. Manifest dry-run

Прогон `python tools/release_manifest.py --repo-root <worktree> --dry-run` на
чистом дереве код-кандидата `1647fe132`. В worktree нет `.deploy/release.json`,
поэтому для `previous_*` использован локальный untracked seed с прод-идентичностью
`a64ecb89b / 2.58.250` (удалён сразу после прогона; ни одно поле не выдумано):

```json
{
  "deployed_at": "2026-11-26T00:00:38.018263Z",
  "deployed_sha": "1647fe13234f161cfa9e7ea0ce78de3c993e841b",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "a64ecb89b0a5930bb37e9a6e73931174f7a8e7ba",
  "previous_version": "2.58.250",
  "release_branch": "release/mod-acl-m1b-2.58.251",
  "schema": 1,
  "version": "2.58.251"
}
```

`deployed_sha` инструмент берёт из `git rev-parse HEAD` момента прогона.
Последний коммит ветки — этот evidence-документ (меняет только `plans/`),
поэтому подтверждающий dry-run на финальном tip'е даёт те же поля с
`deployed_sha` = фактический HEAD; он выполнен после evidence-коммита и
приведён в handoff сборки. Штатная запись манифеста — DevOps на сервере, где
`deployed_sha` = HEAD выложенного checkout.

Контракт выкладки: **DDL 0, миграций 0, новых флагов 0, новых store/endpoint/
планировщиков нет**; `migrations/`, `models/`, `services/pg_db.py`,
`services/database.py` не затронуты (0 файлов в diff base..HEAD);
`config/settings.py` изменён только строкой версии; схема v48. Набор путей
OpenAPI не меняется (websocket/SSE на 2.58.250 отсутствуют; новых маршрутов
срез не добавляет).

## 7. Откат

- **Только код**, `git`-откат на `a64ecb89b0a5930bb37e9a6e73931174f7a8e7ba`
  (2.58.250), `tools/release_manifest.py --effect rollback`.
- DDL 0, миграций 0, новых флагов 0, формат данных не меняется; промпты не
  затрагиваются; пользовательские правки промптов/настроек не страдают.
- Данные production не мигрируются, восстановление БД не требуется.

## 8. Что осталось непроверенным (честно)

- Effective-state прода (фактическая версия, схема, identity деплоя, диск) —
  DevOps после выкладки; здесь production не затрагивался.
- Визуальный контракт: срез меняет сервисный слой принятия решения о правах,
  не UI; `web/*` байт-идентичен базе, поэтому Playwright/Browser Use не
  требовался (ревью: `ui_visual_gate = NOT_APPLICABLE`).
- Живая Telegram-сессия Mini App и живой чат не упражнялись: `initData`
  подписывался локально, продовый токен/сеть не использовались. Это
  ограничение evidence, а не дефект; строки 172/171/S10-13 остаются PENDING.
- Полный 23k-набор не прогонялся до конца (прерван в срезе на 27% и 5%,
  темп среды ~3 ч); вместо него — 62-файловый набор затронутых швов, пины,
  ACL/RBAC/secret-наборы и побитовое сравнение падений с базой.
- Реальное поведение моделей/чатов — не инженерный критерий приёмки
  (`BOUNDED ACCEPTANCE`), наблюдается при эксплуатации.

## 9. Очистка

- Временный `.deploy/release.json` seed удалён сразу после dry-run; каталог
  `.deploy/` удалён (`git status --porcelain` пуст).
- Вспомогательный bump/verify-скрипт — в `%TEMP%\opencode\m1b251`, репозиторий
  не затрагивал; лог-файлы сравнения падений там же.
- Новых файлов вне среза, version wave и этого документа нет. Deploy/merge в
  master/SSH не выполнялись. Worktree `...-a833f258` — активная линия релиза,
  сохраняется до завершения выкладки/ревью.
