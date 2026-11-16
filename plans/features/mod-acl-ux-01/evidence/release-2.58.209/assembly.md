# MOD-ACL-UX-01 M2.1 — релизный кандидат `2.58.209` (без деплоя)

Дата сборки: 17.11.2026. Статус: **assembly done / REVIEW**, production не
трогался, деплой не выполнялся, `VERIFIED` не заявляется.

- Ветка: `release/mod-acl-m21-2.58.209`.
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\mod-acl-m21-2-58-209-a85c7e98549b-50581165`
  (unit `release-2.58.209`, зарегистрирован глобальным housekeeping).
- База/прод/откат: `a3262403` (`2.58.208`, deployed 17.11.2026, health 200,
  schema 47; внутри SMART/LLM/disk/P0-PROD-DISK и VMQ recent-window).
- Линия M2.1: `bca18c1e` (docs-база 2.58.205). От неё перенесены только
  product/test коммиты; docs-коммиты линии (`0585f238`, `299ac2b7` и прочие
  evidence-доки), старый bump `afcaf95f`, ветка
  `release/mod-acl-m21-2.58.206` и evidence 2.58.206 **не переносились**.
- Bump: `e45335c2` (30 файлов / 31 строка версии).

## 1. Перенос коммитов

Порядок `git cherry-pick` поверх `a3262403`:

| Исходный (M2.1) | Новый SHA | Содержание |
|---|---|---|
| `be8e8ecf` | `0a47f16a` | feat per-chat adapters для 12 потребителей модулей |
| `def84275` | `eb556b51` | recheck media-download callback per chat |
| `b278a547` | `1e068dcc` | remove product master-AND per chat |
| `9b78b6ab` | `991caf12` | test-only: снятие тавтологичных pool/model-ассертов |
| `1a417917` | `64cd6f5f` | per-chat publish, force-repeat, persona frame (D1–D3) |
| `bd92838d` | `79a03b3a` | test-only: F1 test-debt + коммитнутый due-scan per-chat тест |
| `aa130334` | `68c82c80` | terminal outcome для `disabled` (Approved 17.11.2026) |
| — | `e45335c2` | bump `2.58.208 → 2.58.209` (пины) |

Конфликт был ровно один: `9b78b6ab` менял `evidence/m21/pytest-green.txt|xml`,
которые в базе `a3262403` отсутствуют (старые evidence не переносятся).
Разрешено удалением этих двух файлов; тестовая правка `9b78b6ab` применена.
Продуктовых конфликтов и конфликтов пинов не было — M2.1-коммиты пины версии
не содержат. Подробно: `conflicts.md`.

Диапазон `a3262403..e45335c2`: **69 файлов, +2271/−296**:
- 39 product/test файлов M2.1: +2240/−265;
- 30 файлов пинов `2.58.208 → 2.58.209`: 31 строка (APP_VERSION, meta,
  24 py-пина, 4 JS-пина, polygon ×2). BOM/CRLF сохранены, JS-пины в
  escaped-форме `2\.58\.209`.

`deploy_v2.9.2.py` не изменялся.

## 2. Проверенный контракт M2.1

- **Входной гейт инициативы**: единственная per-chat проверка
  `initiative_observer.initiative_chat_enabled` (канонический
  `chat_params`-резолвер: GLOBAL `flags.initiative_enabled` → CHAT
  `initiative.enabled`; env `MCA_INTENTS_ENABLED` — отдельный
  `emergency_block`). Используется наблюдателем, `mca_intents`
  (`create_intent/list_active/due_candidates`) и
  `direct_chat_service.handle_initiative`.
- **`disabled` — один терминальный исход**: ветка `status == "disabled"`
  в `InitiativeObserverRunner` даёт `capability_blocked += 1` и ровно одно
  событие `initiative_publication_cancelled` с `stage=capability:entry`,
  `reason_code=capability_off`; `_record_result`/`initiative_decided` не
  вызываются (решения не было). Событие публикации после генерации остаётся
  прежним `stage=capability:off` (publish guard).
- **`publish_guard` не изменён**: AST-сегмент функции в
  `services/initiative_observer.py` побайтно равен базе
  (sha256 `1d8a854c0af7…`).
- **`resolve_capability` не изменён**: AST-сегмент в `services/chat_params.py`
  равен базе (sha256 `fa658447e493…`); расширена только соседняя
  `resolve_param_capability` (authoritative `global_value/global_source`).
- **`mca_events` не изменён**: файл побайтно равен базе
  (sha256 `8a6f67b65232…`).
- **ACL не расширен**: в диффе нет acl/rbac/auth-файлов; в
  `web/api/stories.py` ACL-проверка чата перенесена **до** per-chat гейта
  (ужесточение, не расширение).
- **UI M2.1 не меняет**: в диффе нет `web/app.js`, шаблонов, CSS или
  Mini App-ассетов; изменён только `web/api/stories.py`.

## 3. Инварианты

- `APP_VERSION=2.58.209`, Settings 472 поля.
- Схема БД: `MigrationStep` 47 (max 47), DDL 0, новых миграций нет.
- Каталог параметров: REGISTRY 645 / GROUPS 121 / `_TAB_BY_GROUP` 119 /
  TAB_RULES 22; `tools/gen_param_registry_round1025.py --check` → `CHECK OK`.
- Новых флагов, миграций, промптов, моделей, composer-правок и
  планировщиков нет.
- Заводские/пользовательские настройки 2.58.208 не сбрасываются; PG
  `models.llm_timeout=180` / `models.llm_total_budget=360` этим кандидатом
  не меняются.

## 4. Тесты

Полные данные и точные команды: `tests-2.58.209.json`. Кратко (post-bump):

| Набор | Результат |
|---|---|
| M2/M2.1 (`_m2_*`, `_01_m21_gates`, `_01_m21_adapters`, `_m2_inflight`) | 118 passed, 0 failed |
| Изменённые seams (asap7/asap8/mca09/mca12/mca18/smoke) | 196 passed |
| Nostalgia-набор (10 файлов) | 217 passed |
| Веб-пины + инварианты (24 файла) | 856 passed, 4 pre-existing failed |
| VMQ recent-window (регрессия 2.58.208) | 30 passed |
| SMART/чекап/tool-loop/transport (регрессия 2.58.208) | 368 passed |
| Disk/status/identity/manifest (регрессия 2.58.208) | 277 passed, 1 pre-existing failed |
| Changed seams + webapp JS unit (2.58.208) | 260 passed |
| JS-пины (node, 4 файла) | 4 passed |
| ACL M1/M3/M4 + semantic checkpoint | 44 passed |
| `test_initiative_coordination.py` | 56 passed, 4 pre-existing failed |

Все 9 падений воспроизведены на чистой базе `a3262403` с теми же node id
(см. `pre_existing` в JSON) и не связаны с M2.1:
- 4 × `test_initiative_coordination.py` (wall-clock NOW-фикстуры и
  `tools/rlr_live_proof.py` seam);
- 1 × `test_hotfix_round1025_cachebust.py::test_version_bumped_and_matches_readme`
  (README содержит v2.58.174; README вне утверждённого набора пинов);
- 4 × `test_tool_coordinator_round1026.py` / `test_unified_image_request_round1026.py`
  (устаревшие baseline-ассерты канона инструментов: 18 vs 17 и forbidden-paths).

## 5. Манифест и откат

`manifest-dry-run.json`: чистое tracked-дерево, `version=2.58.209`,
`dirty_tracked=false`, `deployed_sha=e45335c2…` (content tip),
`previous_sha=a3262403…`, `release_branch=release/mod-acl-m21-2.58.209`.
`.deploy/` после прогона удалён; production-файлы не читались.

`rollback.json`: цель отката `a3262403` (2.58.208), schema 47, DDL 0,
миграций/изменений данных нет.

## 6. Ограничения

- Деплоя и production-проверок в этом артефакте нет.
- REVIEW, не VERIFIED: нужно независимое ревью кандидата.
- Pre-existing падения зафиксированы, но не исправлялись (BACKLOG_ONLY).
- Реальный Telegram-сценарий (чат OFF → нет публикации; GLOBAL OFF + CHAT ON
  → публикация) остаётся post-deploy проверкой.
