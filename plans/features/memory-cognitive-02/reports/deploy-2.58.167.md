# Deploy 2.58.167 — MEMORY-07: аддитивная схема сообществ (v43 → v44)

Адресат: **production** (192.255.209.205, `/var/www/admin_bot`).
Причина выкладки: одобренный Reviewer шаг схемы `8b5907b0` (v44, `mca_community_*`)
+ релизный бамп версии. Продуктовое поведение не меняется: шаг только создаёт
таблицы, код этой волны их не читает и не пишет.

## 1. Привязка кандидата

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.167` = `153063b2826228b699786c911151b4348555bd48` |
| Одобренный кандидат | `8b5907b0` (parent `8d9b3779`) |
| Релизный коммит | `153063b2` = `8b5907b0` + бамп версии (31 файл, 33/33) |
| Предыдущий прод | 2.58.166 @ `b2744b58` |
| MUTABLE_WORKTREE_REQUIRED | **no** — иммutабельный checkout по SHA, `dirty_after=0` |
| Repo write scope выкладки | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 24 py-пина + 4 js-пина |

Дельта `b2744b58..8b5907b0` (9 файлов, 682 вставки / 23 удаления):

| Файл | Суть |
|---|---|
| `services/memory_communities.py` (+114, новый) | **владелец DDL**: `COMMUNITY_BUILDS_DDL_SQLITE`, `COMMUNITY_MEMBERS_DDL_SQLITE`, `COMMUNITY_INDEX_DDL` (везде `IF NOT EXISTS`), имя шага `memory_communities_v44` |
| `services/database.py` (+67) | `_SCHEMA_VERSION_MEMORY_COMMUNITIES = 44`, регистрация `MigrationStep(44, …)`, `_migrate_communities_v44()` применяет DDL владельца; собственных копий DDL нет |
| `tests/test_memory_communities_migration.py` (+280) | новые тесты шага (partial-state, truncated-file, no-op) |
| 5 файлов тестов (пины) | хвост схемы 43 → 44 |
| `plans/…` (3 файла) | docs |

`user_version`/DDL-инварианты: шаг аддитивный, `nodes`/`edges`/`graph_facts` не
меняются, backfill нет, PG — no-op. Чтений/записей новых таблиц в этой волне нет:
единственное обращение в живом коде — `services/mca_retrieval_context.py`
(`_community_candidates`) — **существующее с 2.58.166** и защищённое проверкой
наличия таблицы: до миграции таблицы нет → `[]`, после — таблица пуста → `[]`;
канал `community` добавляется только при непустой выдаче. Записей нет ни в одном файле.

## 2. Преддеплойная валидация (точный кандидат, локально)

Python `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, cwd — worktree кандидата,
`-p no:cacheprovider`.

| Проверка | Результат |
|---|---|
| Миграция + идентичность + 5 пинов (`test_memory_communities_migration`, `test_memory_identity`, `test_evol014`, `test_evol016`, `test_mca17c_1047`, `test_ur_c_sched`) | **104 passed** |
| `tests -k "memory or graphrag or mca07 or mca22 or dossier or retrieval"` | **1592 passed, 3 failed, 1 error** |
| Пины версии после бампа (24 py) | **860 passed, 0 failed** |
| JS-пины (hotfix 7/8/9/10) | **4/4 OK** (`node`, exit 0) |
| Повтор миграции+идентичности после бампа | **35 passed** |

Классификация падений (набор совпадает с зафиксированным при выкладке 2.58.166):

| Тест | Статус |
|---|---|
| `test_warning_coalesced_not_repeated`, `test_not_serviceable_warning_coalesced`, `test_style_anchors_not_broken` | **pre-existing** — файлы не менялись с `40ae401a` (до базовой 2.58.166), те же падения задокументированы в `deploy-2.58.166.md §2` |
| `test_youtube_…::test_multimodal_success_writes_no_memory` (error) | **pre-existing** — двойник без retired `get_smart_cache`, тот же набор |

## 3. Деплой

Один recon-коннект (read-only) + один деплой-коннект (SSH по ключу, port 22,
`BatchMode`, без паролей и ретраев), по правилам AGENTS.md/fail2ban.

- `git fetch --prune origin` → `153063b2^{commit}` есть; `origin/release/2.58.167` = `153063b2`.
- Снимок данных ДО выкладки: `sqlite3 backup` API → `/tmp/predeploy-258167.db`
  (**1 740 234 752 б**), read-back: `user_version 43`, `quick_check ok`,
  `schema_migrations 32`, `smart_messages 2 073 204`, `nodes 33 243`, `edges 64 431`,
  `graph_facts 23 301`.
- `git checkout -B release/2.58.167 153063b2` → `dirty_after=0`.
- `systemctl restart admin_bot` в **2026-11-08T08:40:57Z**; миграция завершена 08:41:26Z.
- Ретенция: удалены старые снимки `/tmp/predeploy-2581{45..65}.db`, сохранены
  **258166** и **258167** (диск: 27G занято / 67G свободно).

## 4. Постдеплойная проверка

| Проверка | Факт |
|---|---|
| `/healthz` локально | `{"status":"ok","version":"2.58.167"}`, HTTP **200** |
| `/web/`, `/api/health` | 200, 200 |
| Публично `https://admin-bot.duckdns.org/healthz` | 200, `2.58.167` |
| Публично `/web/` | 200, 1 276 327 б, `2.58.167` — **17**, `2.58.166` — **0** |
| Сервис | `active`, `enabled`, `NRestarts=0`, `MainPID 3067777`, с 08:40:59Z |
| Журнал от рестарта | 230 строк, `Traceback` — **0**, `ERROR` — **0**, `WARNING` — 1 |
| Единственный WARNING | `smart_memory: embedding generation not serviceable / smart_archive / superseded` — тот же известный, что в 2.58.166 |
| Served asset | `/web/app.js` 2 062 901 б, sha256 `495d4882…c3050c6`, **`cmp` identical** с checkout |
| Memory-воркеры | `MemoryMaintenance started (merge/True/7d, review/True/3d, wal/True/6h, embed_reprobe=600s, intent_hb=300s)` |

### Схема и миграция

| Метрика | До | После |
|---|---|---|
| `user_version` | 43 | **44** |
| `schema_migrations` | 32 | **33** (+1, `memory_communities_v44`) |
| таблиц (без `sqlite_*`) | 125 | **127** (+`mca_community_builds`, `mca_community_members`) |
| индексы сообществ | — | **3** (`idx_mca_community_builds_chat_status`, `idx_mca_community_members_node`, `idx_mca_community_members_community`) |
| `mca_community_builds` | нет таблицы | есть, **0 строк** |
| `mca_community_members` | нет таблицы | есть, **0 строк** |
| `quick_check` | ok | **ok** (`integrity_check` тоже ok) |
| DDL/индексы `nodes`, `edges`, `graph_facts`, `smart_messages`, `mca_entity_canonical`, `graph_facts_vec`, `schema_migrations` | — | **идентичны** снимку |

Журнал миграции (выдержка, точные строки):

```
08:41:02 [database] migrations: start | current user_version=43 | pending=[44]
08:41:02 [database] migration backup-guard: start | target_version=43 (VACUUM INTO + read-back)
08:41:26 memory_backup: pre-migration copy created + read-back ok | target_version=43
08:41:26 [disk_retention] migration backup rotated out | name=pre_migration_20261107_155353.db
08:41:26 [database] migration backup-guard: done in 24.1s
08:41:26 [database] migration v44: mca_community_builds, mca_community_members
08:41:26 [database] migration v44 applied in 0.0s | memory_communities_v44
08:41:26 [database] migrations: complete | user_version=44 | total 24.1s
```

### Счётчики строк: снимок → прод

| Таблица | Снимок до деплоя | После рестарта | Δ |
|---|---|---|---|
| `smart_messages` | 2 073 204 | 2 073 211 (позже 2 073 213) | +7…+9, все — новые id 2 395 433+ |
| `nodes` | 33 243 | 33 243 | 0 |
| `edges` | 64 431 | 64 431 | 0 |
| `graph_facts` | 23 301 | 23 301 | 0 |
| `schema_migrations` | 32 | 33 | +1 |
| `mca_community_builds` | нет | 0 | — |
| `mca_community_members` | нет | 0 | — |

Рост `smart_messages` — **только дозапись живого трафика**: все строки с
`id <= 2 395 432` (то есть весь снимок) на месте — `2 073 204` из `2 073 204`
(`intact=True`), удалений нет; в журнале после рестарта видна обработка нового
сообщения владельческого чата (`chat_id=-1002661910336 | message_id=1205044`, 08:43:58Z).

## 5. Покрытие требований

| Строка карты | Чем закрыта в этой выкладке | Статус строки |
|---|---|---|
| MEMORY-07 (клаузула «v44 applied on fresh+legacy DB with repeat no-op») | v44 применён на реальной прод-БД 1.74 ГБ: `pending=[44]` → `user_version=44`, +2 таблицы, +1 строка книги, DDL существующих таблиц не изменён, `quick_check ok`; no-op повтора подтверждён тестами и прогоном Reviewer на копии 1.67 ГБ | строка остаётся **PENDING** (остальная часть — сборка сообществ, веса, lifecycle — не реализована) |
| MEM-07.1…07.6 (build, веса рёбер, lifecycle, подписи, стабильность ID, ассоциации) | **не входят в эту волну**, код не менялся | PENDING (как и было) |
| MEM-06.* / MEM-06-RUNTIME | код не менялся; регресс-набор памяти 1592 passed (3 pre-existing failed), профильные пин-тесты зелёные | без изменений |

## 6. Gate

`requirements_gate.py check --repo . --map …/requirements-map.json --stage release
--candidate 153063b2 --deployed-commit 153063b2` → `inventory=153 manual=146
scoped=146 errors=148`, exit 1. Состав ошибок тот же, что при 2.58.166: карта
уровня эпика привязана к `2141b020` (`candidate mismatch`) и содержит
незакрытые чужие строки (`MEMORY-00`, `INV-*`, `MEMORY-07` build-волна и др.).
Slice-graph в карте отсутствует (`slice_graph_path` пуст) → валидированного
срезового прогона нет. Эпик остаётся не-DONE; это корректное состояние, а не
дефект выкладки.

## 7. Что НЕ проверено

- Сборка сообществ (`B4`), веса рёбер, lifecycle — **вне волны**: таблицы пусты
  и инертны, гейт `MCA_MEMORY_COMMUNITIES_ENABLED` default OFF.
- Живой тематический retrieval после появления пустых таблиц специально не
  инспектировался на реальном чате: канал `community` возвращает `[]` до первой
  сборки (проверено кодом и тестами), отправок в чаты владельца не было.
- Владельческие UI/устройство-проверки — вне объёма (owner_optional).
- `web/style.css` в этом релизе отсутствует (`sha256sum` предупредил) — не
  относится к изменению: ассеты не менялись, `app.js` сверен побайтово.

## 8. Откат

- Кодовый: `git checkout release/2.58.166` (= `b2744b58`) → `systemctl restart admin_bot`.
  Объект `b2744b58^{commit}` на сервере подтверждён (`rollback_present=yes`),
  сервис `enabled`.
- Снимки данных: `/tmp/predeploy-258167.db` (1 740 234 752 б, read-back ok) и
  `/tmp/predeploy-258166.db`.
- Схемный откат не нужен: v44-таблицы старым кодом не читаются (`DROP` не требуется),
  `user_version` на старом коде остаётся 44 — старый код сверяет только
  собственные шаги и продолжает работать.
- Независимый бэкап владельца: `WorkspaceData/backups/adminbot-postmigration-2026-10-29/`.

## 9. Гигиена

Прогоны и вывод проб:
`…\WorkspaceData\runs\c742e4de9e92c489\memory-cognitive-02-52a705214107\probe-d5fadd0964\`
(`recon_258167.sh`, `deploy_258167.sh`, `final_258167.sh`, `compare_258167.sh`,
`attribute*.sh`, `deploy-258167.out`, `final-258167.out`, `compare-258167.out`,
`gate-release-258167.txt`) — сохранены для воспроизведения, снимаются при закрытии эпика.
На сервере одноразовые артефакты проб (`/tmp/served-app-258167*.js`,
`/tmp/served-index-258167*.html`, `/tmp/pub-index-258167.html`) остаются до
следующей выкладки вместе со снимками.
